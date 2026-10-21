"""FIX-67b: серверная защита от повторного «Разобрать текст (ИИ)».

Фронтенд блокирует кнопку на время запроса, но сервер не защищён: двойной клик, повтор сети, две вкладки
дописывали дубли строк. Теперь: (1) пока разбор заявки идёт — второй запрос не ставит задачу и не пишет строки;
(2) запись строк идемпотентна по job (повторный запуск задачи не дублирует). Сеть и LLM — моки.
"""

import pytest
from ai.models import AIJob
from rest_framework.test import APIClient

from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from sourcing.tasks_ai import FEATURE_HANDLERS

URL = "/api/v1/sourcing/parse-request-text/"
TEXT = "Нужны рельсы Р65, 500 тонн, и накладки к ним — 40 штук"
ROWS = [
    {"name": "Рельс Р65", "name_canonical": "Рельс Р65", "quantity": 500, "unit": "т", "unit_code": "TNE"},
    {"name": "Накладка", "name_canonical": "Накладка", "quantity": 40, "unit": "шт.", "unit_code": "PCE"},
]


@pytest.fixture
def words_quote(scene):
    deal = Deal.objects.create(
        title="Заявка: Buyer", company=scene["buyer"], stage=DealStage.objects.get(code="CALCULATING"), notes=TEXT
    )
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=scene["seller_user"],
        seller_company=scene["seller"],
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def api(scene):
    return _client(scene["seller_user"])


@pytest.fixture
def published(monkeypatch, settings):
    """Настоящая `enqueue_ai_job` (строка AIJob, 202), но публикация в брокер подменена — запоминаем вызовы."""
    settings.AI_IMPORT_ENABLED = True
    sent = []

    def fake_apply_async(args=None, task_id=None, **kwargs):
        sent.append((args, task_id))

    monkeypatch.setattr("sourcing.ai_jobs.run_ai_job.apply_async", fake_apply_async)
    return sent


@pytest.fixture
def extract(monkeypatch):
    """Подмена LLM-извлечения; в списке `calls` — сколько раз его вызвали."""
    calls = []

    def fake(content, filename, **kwargs):
        calls.append(content)
        return [dict(row) for row in ROWS]

    monkeypatch.setattr("ai.services.intake.extract_request_items", fake)
    return calls


def _payload(quote, user, job_id):
    return {"quote_id": quote.id, "user_id": user.id, "job_id": job_id}


def _names(quote):
    return [item.imported_raw_name for item in quote.items.order_by("position")]


# --- 1. In-flight-блокировка ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_double_post_queues_one_job_and_returns_the_same_task(words_quote, api, published):
    first = api.post(URL, {"quote_id": words_quote.id}, format="json")
    second = api.post(URL, {"quote_id": words_quote.id}, format="json")

    assert first.status_code == 202 and second.status_code == 202
    assert second.json()["task_id"] == first.json()["task_id"]
    assert second.json()["already_running"] is True
    assert "already_running" not in first.json()
    assert len(published) == 1
    assert AIJob.objects.filter(feature="parse_request_text").count() == 1


@pytest.mark.django_db
def test_teammate_gets_409_while_a_parse_of_the_quote_is_running(words_quote, api, published, scene):
    api.post(URL, {"quote_id": words_quote.id}, format="json")

    response = _client(scene["teammate"]).post(URL, {"quote_id": words_quote.id}, format="json")

    assert response.status_code == 409
    assert response.json() == {"detail": "PARSE_ALREADY_RUNNING"}
    assert len(published) == 1


@pytest.mark.django_db
def test_parse_of_another_quote_is_not_blocked(words_quote, api, published, scene):
    other_deal = Deal.objects.create(
        title="Другая", company=scene["buyer"], stage=DealStage.objects.get(code="CALCULATING"), notes=TEXT
    )
    other = Quote.objects.create(
        deal=other_deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"), prepared_by=scene["seller_user"]
    )
    api.post(URL, {"quote_id": words_quote.id}, format="json")

    response = api.post(URL, {"quote_id": other.id}, format="json")

    assert response.status_code == 202 and "already_running" not in response.json()
    assert len(published) == 2


@pytest.mark.django_db
def test_repeat_after_the_job_finished_is_a_new_parse(words_quote, api, published, extract, scene):
    first = api.post(URL, {"quote_id": words_quote.id}, format="json").json()["task_id"]
    FEATURE_HANDLERS["parse_request_text"](_payload(words_quote, scene["seller_user"], first))

    second = api.post(URL, {"quote_id": words_quote.id}, format="json")

    assert second.status_code == 202 and "already_running" not in second.json()
    assert second.json()["task_id"] != first
    assert len(published) == 2


@pytest.mark.django_db
@pytest.mark.parametrize("outcome", ["error_code", "exception"])
def test_lock_is_released_when_the_task_fails(words_quote, api, published, scene, monkeypatch, outcome):
    first = api.post(URL, {"quote_id": words_quote.id}, format="json").json()["task_id"]

    def broken(content, filename, **kwargs):
        raise RuntimeError("AI_GATEWAY_UNAVAILABLE") if outcome == "error_code" else KeyError("boom")

    monkeypatch.setattr("ai.services.intake.extract_request_items", broken)
    handler = FEATURE_HANDLERS["parse_request_text"]
    payload = _payload(words_quote, scene["seller_user"], first)
    if outcome == "exception":
        with pytest.raises(KeyError):
            handler(payload)
    else:
        assert handler(payload) == {"error": "AI_EXTRACT_FAILED"}

    again = api.post(URL, {"quote_id": words_quote.id}, format="json")
    assert again.status_code == 202 and "already_running" not in again.json()
    assert len(published) == 2


@pytest.mark.django_db
def test_a_late_finishing_old_job_does_not_release_the_lock_of_a_newer_one(words_quote, api, published, scene, extract):
    from sourcing.parse_text_guard import release

    first = api.post(URL, {"quote_id": words_quote.id}, format="json").json()["task_id"]
    release(words_quote.id, first)  # TTL/страж освободил, потом пришёл новый разбор
    second = api.post(URL, {"quote_id": words_quote.id}, format="json").json()["task_id"]

    release(words_quote.id, first)  # «опоздавший» старый job не снимает чужую блокировку

    third = api.post(URL, {"quote_id": words_quote.id}, format="json")
    assert third.json()["task_id"] == second and third.json()["already_running"] is True


@pytest.mark.django_db
def test_lock_of_a_silently_dead_job_is_taken_over(words_quote, api, published, monkeypatch):
    """Задача упала молча (воркер убит) — результат в backend уже FAILURE: следующий запрос не ждёт TTL."""
    first = api.post(URL, {"quote_id": words_quote.id}, format="json").json()["task_id"]
    monkeypatch.setattr("sourcing.parse_text_guard.job_is_finished", lambda task_id: task_id == first)

    again = api.post(URL, {"quote_id": words_quote.id}, format="json")

    assert again.status_code == 202 and "already_running" not in again.json()
    assert again.json()["task_id"] != first


@pytest.mark.django_db
def test_parallel_takeover_of_a_dead_lock_does_not_release_the_newer_lock(
    words_quote, api, published, monkeypatch, scene
):
    """Два запроса видят «упавший» job; пока первый перехватывает, второй уже поставил новый job и лок.
    Первый обязан снять лок только своего (старого) job — иначе выходят два платных job."""
    from sourcing import parse_text_guard

    first = api.post(URL, {"quote_id": words_quote.id}, format="json").json()["task_id"]
    uid = scene["seller_user"].id

    def finished_and_competitor_wins(task_id):
        if task_id == first:
            parse_text_guard.release(words_quote.id, first)  # конкурент снял устаревший лок…
            assert parse_text_guard.acquire(words_quote.id, uid)  # …занял свой…
            parse_text_guard.attach_task(words_quote.id, uid, "competitor-task")  # …и поставил job
            return True
        return False

    monkeypatch.setattr("sourcing.parse_text_guard.job_is_finished", finished_and_competitor_wins)

    response = api.post(URL, {"quote_id": words_quote.id}, format="json")

    assert response.status_code == 202
    assert response.json() == {"task_id": "competitor-task", "already_running": True}
    assert len(published) == 1  # второй платный job не поставлен


@pytest.mark.django_db
def test_fast_job_finished_before_attach_task_leaves_no_lock(words_quote, api, settings, monkeypatch, scene):
    """AI_DISABLED / QUOTE_NOT_FOUND отрабатывают раньше, чем вьюха записала task_id в лок: лок не должен
    висеть до TTL."""
    from sourcing.parse_text_guard import holder

    settings.AI_IMPORT_ENABLED = True
    finished = set()

    def run_job_at_once(args=None, task_id=None, **kwargs):
        monkeypatch.setattr("ai.services.intake.extract_request_items", lambda c, f, **k: [dict(r) for r in ROWS])
        FEATURE_HANDLERS["parse_request_text"]({**args[1], "job_id": task_id})
        finished.add(task_id)

    monkeypatch.setattr("sourcing.ai_jobs.run_ai_job.apply_async", run_job_at_once)
    monkeypatch.setattr("sourcing.parse_text_guard.job_is_finished", lambda task_id: task_id in finished)

    first = api.post(URL, {"quote_id": words_quote.id}, format="json")

    assert first.status_code == 202
    assert holder(words_quote.id) is None
    again = api.post(URL, {"quote_id": words_quote.id}, format="json")
    assert "already_running" not in again.json() and again.json()["task_id"] != first.json()["task_id"]


@pytest.mark.django_db
def test_attach_task_never_overwrites_a_lock_it_does_not_own(words_quote, scene):
    from sourcing.parse_text_guard import acquire, attach_task, holder, release

    uid = scene["seller_user"].id
    assert acquire(words_quote.id, uid)
    release(words_quote.id)  # лок снят (TTL/перехват) до attach_task

    attach_task(words_quote.id, uid, "late-task")
    assert holder(words_quote.id) is None  # не воскрешаем снятый лок

    assert acquire(words_quote.id, uid + 1)  # чужой новый лок
    attach_task(words_quote.id, uid, "late-task")
    assert holder(words_quote.id) == (None, uid + 1)


@pytest.mark.django_db
def test_lock_is_taken_atomically_with_a_ttl_longer_than_the_task_time_limit(words_quote, api, published, monkeypatch):
    from django.core.cache import cache

    added = []
    real_add = cache.add

    def spy(key, value, timeout=None, **kwargs):
        added.append((key, timeout))
        return real_add(key, value, timeout, **kwargs)

    monkeypatch.setattr(cache, "add", spy)
    api.post(URL, {"quote_id": words_quote.id}, format="json")

    assert len(added) == 1
    assert added[0][1] > 600  # жёсткий лимит задачи run_ai_job — 600 с


@pytest.mark.django_db
def test_lock_is_released_when_publishing_to_the_broker_fails(words_quote, api, settings, monkeypatch):
    from kombu.exceptions import OperationalError

    settings.AI_IMPORT_ENABLED = True

    def down(*args, **kwargs):
        raise OperationalError("broker down")

    monkeypatch.setattr("sourcing.ai_jobs.run_ai_job.apply_async", down)
    assert api.post(URL, {"quote_id": words_quote.id}, format="json").status_code == 500

    monkeypatch.setattr("sourcing.ai_jobs.run_ai_job.apply_async", lambda **kwargs: None)
    assert api.post(URL, {"quote_id": words_quote.id}, format="json").status_code == 202


@pytest.mark.django_db
def test_refused_requests_do_not_take_the_lock(words_quote, api, published, settings):
    """Права/404/пустой текст отбиваются ДО блокировки — без регрессии прав и без «зависшей» блокировки."""
    from accounts.models import CustomUser

    stranger = CustomUser.objects.create_user(email="x@x.uz", username="x@x.uz", password="pw", is_active=True)
    assert _client(stranger).post(URL, {"quote_id": words_quote.id}, format="json").status_code == 403
    assert api.post(URL, {"quote_id": 987654}, format="json").status_code == 404

    assert api.post(URL, {"quote_id": words_quote.id}, format="json").status_code == 202
    assert len(published) == 1


# --- 2. Идемпотентность записи -------------------------------------------------------------------------


@pytest.mark.django_db
def test_rerun_of_the_same_job_does_not_duplicate_lines_nor_pay_again(words_quote, scene, extract):
    job = AIJob.objects.create(celery_task_id="job-retry", owner=scene["seller_user"], feature="parse_request_text")
    handler = FEATURE_HANDLERS["parse_request_text"]
    payload = _payload(words_quote, scene["seller_user"], job.celery_task_id)

    first = handler(payload)
    again = handler(payload)  # ретрай / повторная доставка того же job

    assert first["added"] == 2
    assert again["added"] == 2 and again["quote_id"] == words_quote.id  # прежний итог, а не «0 строк»
    assert _names(words_quote) == ["Рельс Р65", "Накладка"]
    assert len(extract) == 1  # повторный платный вызов LLM не делался


@pytest.mark.django_db
def test_two_concurrent_workers_of_the_same_job_write_once(words_quote, scene, extract, monkeypatch):
    """Гонка внутри записи: оба прошли ранюю проверку, но применить результат job может только один."""
    from crm.services.quotes.bulk import import_extracted_lines_into_quote

    job = AIJob.objects.create(celery_task_id="job-race", owner=scene["seller_user"], feature="parse_request_text")
    user = scene["seller_user"]

    first = import_extracted_lines_into_quote(words_quote, user, ROWS, job_id=job.celery_task_id)
    second = import_extracted_lines_into_quote(words_quote, user, ROWS, job_id=job.celery_task_id)

    assert first == (2, False, None) and second == (2, False, None)
    assert QuoteItem.objects.filter(quote=words_quote).count() == 2


@pytest.mark.django_db
def test_a_new_job_for_the_same_quote_appends_again(words_quote, scene, extract):
    """Новый разбор — осознанное действие: другой job дописывает строки (как и раньше)."""
    handler = FEATURE_HANDLERS["parse_request_text"]
    for name in ("job-a", "job-b"):
        AIJob.objects.create(celery_task_id=name, owner=scene["seller_user"], feature="parse_request_text")
        handler(_payload(words_quote, scene["seller_user"], name))

    assert QuoteItem.objects.filter(quote=words_quote).count() == 4


@pytest.mark.django_db
def test_failed_write_leaves_the_job_unapplied_so_a_retry_can_succeed(words_quote, scene, extract, monkeypatch):
    job = AIJob.objects.create(celery_task_id="job-rollback", owner=scene["seller_user"], feature="parse_request_text")
    handler = FEATURE_HANDLERS["parse_request_text"]
    payload = _payload(words_quote, scene["seller_user"], job.celery_task_id)

    def boom(quote_id):
        raise RuntimeError("recalc failed")

    monkeypatch.setattr("crm.services.quotes.bulk.QuoteCalculationService.recalculate_quote", boom)
    with pytest.raises(RuntimeError):
        handler(payload)
    job.refresh_from_db()
    assert job.applied_rows is None and QuoteItem.objects.filter(quote=words_quote).count() == 0
