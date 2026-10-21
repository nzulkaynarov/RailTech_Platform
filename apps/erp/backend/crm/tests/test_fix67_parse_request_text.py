"""FIX-67: заявка словами → строки КП через существующий ИИ-разбор (`ai.services.intake`).

Кнопка «Разобрать текст в строки (ИИ)» в конструкторе КП: сервер берёт текст заявки сам (клиент текст не
присылает — нечего подделывать), ставит задачу в очередь `ai` (202 + task_id), воркер разбирает текст тем же
извлечением, что файл клиента, и дописывает строки в КП. ИИ выключен / шлюз недоступен — понятный код
(`AI_DISABLED`), а не 500. Платных вызовов нет: извлечение подменено.
"""

import pytest
from portal.models import PortalRequestSummary
from rest_framework.test import APIClient

from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from sourcing.tasks_ai import FEATURE_HANDLERS

URL = "/api/v1/sourcing/parse-request-text/"
TEXT = "Нужны рельсы Р65, 500 тонн, и накладки к ним — 40 штук"


@pytest.fixture
def words_quote(scene):
    """Заявка словами и пустой черновик КП продавца к ней."""
    deal = Deal.objects.create(
        title="Заявка: Buyer", company=scene["buyer"], stage=DealStage.objects.get(code="CALCULATING"), notes=TEXT
    )
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=scene["seller_user"],
        seller_company=scene["seller"],
    )
    return quote


@pytest.fixture
def api(scene):
    client = APIClient()
    client.force_authenticate(scene["seller_user"])
    return client


@pytest.fixture
def queue(monkeypatch):
    """Подмена постановки задачи: запоминает, что ушло в очередь `ai`, и отвечает как настоящая."""
    from rest_framework import status
    from rest_framework.response import Response

    sent = []

    def fake_enqueue(feature, payload, user):
        sent.append((feature, payload, user.id))
        return Response({"task_id": "task-fix67"}, status=status.HTTP_202_ACCEPTED)

    monkeypatch.setattr("sourcing.ai_jobs.enqueue_ai_job", fake_enqueue)
    return sent


@pytest.mark.django_db
def test_without_ai_the_answer_is_a_clear_code_not_a_500(words_quote, api, queue, settings):
    settings.AI_IMPORT_ENABLED = False

    response = api.post(URL, {"quote_id": words_quote.id}, format="json")

    assert response.status_code == 503
    assert response.json() == {"detail": "AI_DISABLED"}
    assert queue == []  # в очередь ничего не ушло


@pytest.mark.django_db
def test_with_ai_the_job_is_queued_for_the_quote(words_quote, api, queue, settings, scene):
    settings.AI_IMPORT_ENABLED = True

    response = api.post(URL, {"quote_id": words_quote.id}, format="json")

    assert response.status_code == 202
    assert response.json() == {"task_id": "task-fix67"}
    assert queue == [
        (
            "parse_request_text",
            {"quote_id": words_quote.id, "user_id": scene["seller_user"].id},
            scene["seller_user"].id,
        )
    ]


@pytest.mark.django_db
def test_a_deal_without_any_text_is_refused_before_the_queue(scene, api, queue, settings):
    settings.AI_IMPORT_ENABLED = True
    deal = Deal.objects.create(title="Пусто", company=scene["buyer"], stage=DealStage.objects.get(code="CALCULATING"))
    quote = Quote.objects.create(
        deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"), prepared_by=scene["seller_user"]
    )

    response = api.post(URL, {"quote_id": quote.id}, format="json")

    assert response.status_code == 400
    assert response.json() == {"detail": "REQUEST_TEXT_EMPTY"}
    assert queue == []


@pytest.mark.django_db
def test_outsider_without_pricing_permission_is_refused(words_quote, queue, settings):
    from accounts.models import CustomUser

    settings.AI_IMPORT_ENABLED = True
    stranger = CustomUser.objects.create_user(email="x@x.uz", username="x@x.uz", password="pw", is_active=True)
    client = APIClient()
    client.force_authenticate(stranger)

    response = client.post(URL, {"quote_id": words_quote.id}, format="json")

    assert response.status_code == 403
    assert queue == []


@pytest.mark.django_db
def test_unknown_quote_is_404(api, queue, settings):
    settings.AI_IMPORT_ENABLED = True
    assert api.post(URL, {"quote_id": 987654}, format="json").status_code == 404
    assert api.post(URL, {}, format="json").status_code == 400


@pytest.mark.django_db
def test_worker_parses_the_request_text_into_quote_lines(words_quote, scene, monkeypatch):
    """Воркер отдаёт извлечению именно текст заявки и дописывает строки в КП."""
    seen = {}

    def fake_extract(content, filename, **kwargs):
        seen["text"], seen["filename"] = content.decode("utf-8"), filename
        return [
            {"name": "Рельс Р65", "name_canonical": "Рельс Р65", "quantity": 500, "unit": "т", "unit_code": "TNE"},
            {"name": "Накладка", "name_canonical": "Накладка", "quantity": 40, "unit": "шт.", "unit_code": "PCE"},
        ]

    monkeypatch.setattr("ai.services.intake.extract_request_items", fake_extract)

    result = FEATURE_HANDLERS["parse_request_text"]({"quote_id": words_quote.id, "user_id": scene["seller_user"].id})

    assert result["added"] == 2 and result["quote_id"] == words_quote.id
    assert seen["text"] == TEXT and seen["filename"].endswith(".txt")
    assert [item.imported_raw_name for item in words_quote.items.order_by("position")] == ["Рельс Р65", "Накладка"]


@pytest.mark.django_db
def test_worker_prefers_the_full_summary_over_the_short_note(words_quote, scene, monkeypatch):
    PortalRequestSummary.objects.create(deal=words_quote.deal, text="Полный текст запроса из Cabinet")
    seen = {}
    monkeypatch.setattr(
        "ai.services.intake.extract_request_items",
        lambda content, filename, **kwargs: seen.setdefault("text", content.decode("utf-8")) and [],
    )

    FEATURE_HANDLERS["parse_request_text"]({"quote_id": words_quote.id, "user_id": scene["seller_user"].id})

    assert seen["text"] == "Полный текст запроса из Cabinet"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "failure, expected",
    [
        (RuntimeError("AI_IMPORT_DISABLED"), "AI_DISABLED"),
        (RuntimeError("AI_GATEWAY_UNAVAILABLE"), "AI_EXTRACT_FAILED"),
        (RuntimeError("AI_EXTRACT_ALL_CHUNKS_FAILED"), "AI_EXTRACT_FAILED"),
    ],
)
def test_worker_degrades_to_a_code_when_the_gateway_is_down(words_quote, scene, monkeypatch, failure, expected):
    def broken(content, filename, **kwargs):
        raise failure

    monkeypatch.setattr("ai.services.intake.extract_request_items", broken)

    result = FEATURE_HANDLERS["parse_request_text"]({"quote_id": words_quote.id, "user_id": scene["seller_user"].id})

    assert result == {"error": expected}
    assert QuoteItem.objects.filter(quote=words_quote).count() == 0


@pytest.mark.django_db
def test_worker_with_nothing_recognised_reports_it(words_quote, scene, monkeypatch):
    monkeypatch.setattr("ai.services.intake.extract_request_items", lambda content, filename, **kwargs: [])

    result = FEATURE_HANDLERS["parse_request_text"]({"quote_id": words_quote.id, "user_id": scene["seller_user"].id})

    assert result == {"error": "IMPORT_NO_LINES"}
