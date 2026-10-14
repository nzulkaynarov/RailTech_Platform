"""R4 (аудит «Номенклатуры», находки D5/D6): ИИ ПРЕДЛАГАЕТ по полям — и остаток лимита виден.

Две связанные вещи в одном файле, потому что это одна волна:

1. **Справочные поля карточки — ВЫБОР из закрытого списка, а не генерация.** Категория и
   единица измерения проходят тот же путь, которым уже закрыт код ТН ВЭД: список кандидатов
   собирается из базы ДО вызова модели, модель выбирает один пункт, и выбор проходит
   ДЕТЕРМИНИРОВАННУЮ сверку с тем же списком. Придуманный id категории уводит карточку не в ту
   ветку каталога молча — продавец этого не заметит, а поиск её больше не найдёт.

2. **Остаток дневного лимита ИИ виден в `/me`.** Это ИНФОРМАЦИЯ, а не новый гейт: проверяем
   не только что число верное, но и что оно НИЧЕГО не запрещает — пользователь с исчерпанным
   лимитом по-прежнему получает `/me` 200.
"""

import pytest
from ai.services.enrich import _accepted_category_id, _accepted_uom_code, enrich_product
from ai.testing import install_fake_gateway

from accounts.models import Company, CompanyMember, CustomUser, WorkspaceRole
from catalog.field_candidates import category_candidates, uom_candidates
from catalog.models import Category, DomainType
from master_data.models import UnitOfMeasure

UOM_CANDIDATES = [{"code": "H87", "name": "шт."}, {"code": "KGM", "name": "кг"}]
CATEGORY_CANDIDATES = [{"id": 11, "name": "Тормозное оборудование"}, {"id": 12, "name": "Подшипники"}]


# ── единица измерения: принимаем только то, что сами и предложили ─────────────


def test_uom_code_from_the_list_is_accepted():
    assert _accepted_uom_code("H87", UOM_CANDIDATES) == "H87"


def test_uom_code_outside_the_list_is_rejected():
    """«PCS» — правдоподобный код UN/ECE, но не наш справочник: в форму он попасть не должен."""
    assert _accepted_uom_code("PCS", UOM_CANDIDATES) == ""


def test_uom_choice_is_matched_case_insensitively_but_returned_canonical():
    assert _accepted_uom_code("h87", UOM_CANDIDATES) == "H87"


def test_uom_empty_answer_and_empty_lookup_stay_empty():
    assert _accepted_uom_code("", UOM_CANDIDATES) == ""
    assert _accepted_uom_code(None, UOM_CANDIDATES) == ""
    # Справочник пуст → кандидатов нет → любой код модели отвергается.
    assert _accepted_uom_code("H87", []) == ""


# ── категория: чужой id — это молчаливая порча мастер-данных ──────────────────


def test_category_id_from_the_list_is_accepted():
    assert _accepted_category_id(11, CATEGORY_CANDIDATES) == 11
    assert _accepted_category_id("12", CATEGORY_CANDIDATES) == 12


def test_foreign_category_id_is_rejected():
    """id существует где-то в базе, но в СПИСКЕ его не было — значит, он не выбран, а выдуман."""
    assert _accepted_category_id(9999, CATEGORY_CANDIDATES) is None


def test_zero_and_garbage_mean_nothing_matched():
    assert _accepted_category_id(0, CATEGORY_CANDIDATES) is None
    assert _accepted_category_id("Тормозное оборудование", CATEGORY_CANDIDATES) is None
    assert _accepted_category_id(None, CATEGORY_CANDIDATES) is None
    assert _accepted_category_id(11, []) is None


# ── retrieval: списки собираются из базы ──────────────────────────────────────


@pytest.mark.django_db
def test_uom_candidates_come_from_the_lookup():
    codes = [row["code"] for row in uom_candidates()]
    assert "H87" in codes  # посеян миграцией master_data/0005 (UN/ECE Rec 20)
    assert all(isinstance(row["name"], str) for row in uom_candidates())


@pytest.mark.django_db
def test_inactive_units_are_not_offered():
    UnitOfMeasure.objects.filter(code="H87").update(is_active=False)
    assert "H87" not in [row["code"] for row in uom_candidates()]


@pytest.mark.django_db
def test_empty_uom_lookup_yields_no_candidates():
    """Справочник пуст — работа не блокируется, просто предлагать нечего."""
    UnitOfMeasure.objects.all().delete()
    assert uom_candidates() == []


@pytest.mark.django_db
def test_category_candidates_are_filtered_by_domain_when_it_is_known():
    Category.objects.all().delete()
    goods = DomainType.objects.get_or_create(code="GENERAL_GOODS", defaults={"name": "Товары"})[0]
    services = DomainType.objects.get_or_create(code="SERVICES", defaults={"name": "Услуги"})[0]
    own = Category.objects.create(name="Металлопрокат", domain_type=goods)
    foreign = Category.objects.create(name="Логистика и перевозка", domain_type=services)
    # Категория без домена доменом не ограничена и годится любому товару — остаётся в списке.
    domainless = Category.objects.create(name="Прочее", domain_type=None)

    ids = [row["id"] for row in category_candidates("Труба стальная", domain_code="GENERAL_GOODS")]

    assert own.id in ids
    assert domainless.id in ids
    assert foreign.id not in ids


@pytest.mark.django_db
def test_category_candidates_without_a_domain_span_the_whole_tree():
    Category.objects.all().delete()
    services = DomainType.objects.get_or_create(code="SERVICES", defaults={"name": "Услуги"})[0]
    service_category = Category.objects.create(name="Логистика и перевозка", domain_type=services)

    ids = [row["id"] for row in category_candidates("Перевозка вагонов")]

    assert service_category.id in ids


@pytest.mark.django_db
def test_category_candidates_show_the_parent_branch():
    """«Инструмент» под разными ветками — разные вещи, поэтому имя идёт с родителем."""
    Category.objects.all().delete()
    parent = Category.objects.create(name="Подвижной состав и части")
    child = Category.objects.create(name="Тормозное оборудование", parent=parent)

    names = {row["id"]: row["name"] for row in category_candidates("Тормозная колодка")}

    assert names[child.id] == "Подвижной состав и части / Тормозное оборудование"


@pytest.mark.django_db
def test_inactive_categories_are_not_offered():
    Category.objects.all().delete()
    hidden = Category.objects.create(name="Устаревшая ветка", is_active=False)

    assert hidden.id not in [row["id"] for row in category_candidates("что угодно")]


# ── enrich целиком: предложение с проверенными полями ─────────────────────────


def _stub_client(monkeypatch, payload, captured=None):
    """Подменяет вызов модели (фейковый шлюз LiteLLM) ответом `payload`; в `captured` — тела запросов."""
    install_fake_gateway(monkeypatch, sink=captured).reply_json(payload)


@pytest.mark.django_db
def test_enrich_proposes_verified_category_and_uom(settings, monkeypatch):
    settings.AI_IMPORT_ENABLED = True
    Category.objects.all().delete()
    goods = DomainType.objects.get_or_create(code="GENERAL_GOODS", defaults={"name": "Товары"})[0]
    category = Category.objects.create(name="Тормозное оборудование", domain_type=goods)
    captured = []
    _stub_client(
        monkeypatch,
        {
            "description": "Композитная тормозная колодка.",
            "specifications": [{"key": "Материал", "value": "Композит"}],
            "suggested_category_hint": "Тормозное оборудование",
            "hs_code_choice": "",
            "category_id": category.id,
            "uom_code": "H87",
        },
        captured,
    )

    result = enrich_product("Тормозная колодка композитная", domain_code="GENERAL_GOODS")

    assert result["category_id"] == category.id
    assert result["uom_code"] == "H87"
    # Текстовая подсказка никуда не делась — она запасной вариант, когда ничего не подошло.
    assert result["suggested_category_hint"] == "Тормозное оборудование"
    # Кандидаты действительно ушли в промпт: без списка выбирать не из чего.
    prompt = captured[0]["messages"][1]["content"][0]["text"]
    assert f"{category.id} — Тормозное оборудование" in prompt
    assert "H87 — шт." in prompt


@pytest.mark.django_db
def test_enrich_drops_a_foreign_category_and_an_unknown_unit(settings, monkeypatch):
    """Модель вернула id категории ЧУЖОГО домена и код единицы не из справочника — оба отброшены."""
    settings.AI_IMPORT_ENABLED = True
    Category.objects.all().delete()
    services = DomainType.objects.get_or_create(code="SERVICES", defaults={"name": "Услуги"})[0]
    DomainType.objects.get_or_create(code="GENERAL_GOODS", defaults={"name": "Товары"})
    foreign = Category.objects.create(name="Логистика и перевозка", domain_type=services)
    _stub_client(
        monkeypatch,
        {
            "description": "Тормозная колодка.",
            "specifications": [],
            "suggested_category_hint": "Тормозное оборудование",
            "hs_code_choice": "",
            "category_id": foreign.id,
            "uom_code": "PCS",
        },
    )

    result = enrich_product("Тормозная колодка", domain_code="GENERAL_GOODS")

    assert result["category_id"] is None
    assert result["uom_code"] == ""
    # Ничего не подошло — но подсказка осталась, по ней продавец заведёт недостающую ветку.
    assert result["suggested_category_hint"] == "Тормозное оборудование"


@pytest.mark.django_db
def test_enrich_survives_empty_lookups(settings, monkeypatch):
    """Справочники пусты — блоков в промпте нет, поля пустые, обогащение работает."""
    settings.AI_IMPORT_ENABLED = True
    Category.objects.all().delete()
    UnitOfMeasure.objects.all().delete()
    captured = []
    _stub_client(
        monkeypatch,
        {
            "description": "Болт М12.",
            "specifications": [],
            "suggested_category_hint": "",
            "hs_code_choice": "",
            "category_id": 0,
            "uom_code": "",
        },
        captured,
    )

    result = enrich_product("Болт М12")

    assert result["category_id"] is None
    assert result["uom_code"] == ""
    assert result["description"].startswith("Болт")
    prompt = captured[0]["messages"][1]["content"][0]["text"]
    assert "Кандидаты категории" not in prompt
    assert "Единицы измерения" not in prompt


# ── остаток дневного лимита ИИ в /me: информация, а не гейт ───────────────────


def _member(email, company):
    role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(user=user, company=company, role=role, is_active=True, is_primary=True)
    return user


def _seed_ai_jobs(owner, count):
    from uuid import uuid4

    from sourcing.models import AIJob

    for _ in range(count):
        AIJob.objects.create(celery_task_id=str(uuid4()), owner=owner, feature="enrich")


def _capabilities(user):
    from accounts.serializers import MeSerializer

    return MeSerializer(user).data["capabilities"]


@pytest.mark.django_db
def test_me_reports_the_remaining_daily_ai_budget(settings):
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 5
    company = Company.objects.create(name="Remaining Co", inn="910000001")
    user = _member("r4-remaining@x.test", company)
    _seed_ai_jobs(user, 2)

    caps = _capabilities(user)

    assert caps["ai_daily_cap"] == 5
    assert caps["ai_daily_used"] == 2
    assert caps["ai_daily_remaining"] == 3


@pytest.mark.django_db
def test_the_whole_team_shares_one_daily_bucket(settings):
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 5
    company = Company.objects.create(name="Team Budget Co", inn="910000002")
    colleague = _member("r4-colleague@x.test", company)
    user = _member("r4-teammate@x.test", company)
    _seed_ai_jobs(colleague, 4)

    caps = _capabilities(user)

    assert caps["ai_daily_used"] == 4
    assert caps["ai_daily_remaining"] == 1


@pytest.mark.django_db
def test_unlimited_is_distinguishable_from_nothing_left(settings):
    """`null` ≠ 0: «безлимит» и «остаток исчерпан» — разные сообщения в интерфейсе."""
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 0  # отключённый потолок
    company = Company.objects.create(name="Unlimited Co", inn="910000003")
    user = _member("r4-unlimited@x.test", company)
    _seed_ai_jobs(user, 3)

    caps = _capabilities(user)

    assert caps["ai_daily_cap"] is None
    assert caps["ai_daily_remaining"] is None
    assert caps["ai_daily_used"] == 3  # потрачено видно и при безлимите


@pytest.mark.django_db
def test_the_remaining_budget_follows_new_jobs(settings):
    """Израсходованное считается на каждый вызов — остаток следует за новыми задачами."""
    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 7
    company = Company.objects.create(name="Cached Co", inn="910000004")
    user = _member("r4-cached@x.test", company)
    _seed_ai_jobs(user, 1)

    assert _capabilities(user)["ai_daily_remaining"] == 6
    _seed_ai_jobs(user, 1)
    # Израсходованное не кэшируется — оно как раз и меняется.
    assert _capabilities(user)["ai_daily_remaining"] == 5


@pytest.mark.django_db
def test_exhausted_limit_does_not_forbid_anything_in_me(settings):
    """ГЛАВНОЕ: показ остатка — не гейт. Лимит исчерпан, а `/me` по-прежнему 200."""
    from rest_framework.test import APIClient

    settings.AI_DAILY_JOB_CAP_PER_COMPANY = 2
    company = Company.objects.create(name="Exhausted Co", inn="910000005")
    user = _member("r4-exhausted@x.test", company)
    _seed_ai_jobs(user, 5)  # перерасход даже сверх потолка

    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/v1/accounts/users/me/")

    assert response.status_code == 200
    caps = response.json()["capabilities"]
    assert caps["ai_daily_remaining"] == 0  # не отрицательное число
    assert caps["ai_daily_cap"] == 2
    # Остальные способности не тронуты — исчерпанный лимит ничего не выключает.
    assert "permissions" in caps and "can_buy" in caps
