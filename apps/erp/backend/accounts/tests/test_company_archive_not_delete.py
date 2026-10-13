"""
Компанию с историей удалить нельзя — из оборота её выводит архив.

Замер 24-08: `DELETE /api/v1/accounts/companies/{id}/` был дефолтным `ModelViewSet.destroy`
и возвращал **204**, снося каскадом 2448 строк. Вместе с компанией исчезали её сделки, а
участники оставались обезличенными аккаунтами без единого членства — диалог обещал «будет
удалена со всеми связанными данными», но про людей не говорил.

Эталоны единодушны: Odoo отказывает («The partner cannot be deleted because it is used in
Accounting») и предлагает Archive; Salesforce не даёт удалить даже пользователя; Stripe не
удаляет финансовый факт вовсе. Поэтому запрет — приведение к заявленному, а не новый гейт.

Каждый держатель проверяется ОТДЕЛЬНЫМ тестом: перечень, проверенный «в среднем», повторил
бы `test_fully_paid_invoice_takes_no_more` — имя шире, чем измеренное.
"""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)


@pytest.fixture
def operator(db):
    return CustomUser.objects.create_user(
        email="archive.operator@test.uz",
        username="archive_operator",
        password="Probe1234!",
        role=SystemRole.objects.get(code="ADMIN"),
        is_superuser=True,
        is_active=True,
    )


@pytest.fixture
def company(db):
    return Company.objects.create(
        name="Пустая компания",
        inn="907500001",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _delete(user, company):
    return _api(user).delete(f"/api/v1/accounts/companies/{company.pk}/")


# ── Держатели истории — по одному на тест ───────────────────────────────────


def test_empty_company_is_still_deletable(operator, company):
    """Обратная сторона: запрет не превратился в «удалить нельзя ничего». Компания без
    истории — это опечатка оператора, и убрать её он должен."""
    resp = _delete(operator, company)

    assert resp.status_code == 204, resp.content
    assert not Company.objects.filter(pk=company.pk).exists()


def test_company_with_a_deal_is_refused(operator, company, db):
    from crm.models import Deal, DealStage

    Deal.objects.create(title="Заявка", company=company, stage=DealStage.objects.get(code="DRAFT"))

    resp = _delete(operator, company)

    assert resp.status_code == 409
    assert "deals" in resp.json()["detail"]
    assert Company.objects.filter(pk=company.pk).exists()


def test_company_routed_as_seller_is_refused(operator, company, db):
    """Продавца держит его маршрутизация: удаление уносило бы чужую заявку из его очереди."""
    from crm.models import Deal, DealSellerRouting, DealStage

    buyer = Company.objects.create(name="Покупатель", inn="907500002")
    deal = Deal.objects.create(title="Чужая заявка", company=buyer, stage=DealStage.objects.get(code="RFQ_OPEN"))
    DealSellerRouting.objects.create(deal=deal, seller_company=company)

    resp = _delete(operator, company)

    assert resp.status_code == 409
    assert "deals" in resp.json()["detail"]


def test_company_with_a_quote_is_refused(operator, company, db):
    from crm.models import Deal, DealStage, Quote, QuoteStatus

    buyer = Company.objects.create(name="Покупатель КП", inn="907500003")
    deal = Deal.objects.create(title="Заявка", company=buyer, stage=DealStage.objects.get(code="RFQ_OPEN"))
    Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        seller_company=company,
        total_incl_vat=Decimal("100"),
    )

    resp = _delete(operator, company)

    assert resp.status_code == 409
    assert "quotes" in resp.json()["detail"]


def test_company_with_active_members_is_refused(operator, company, db):
    """Главный молчаливый вред: люди. Каскад оставлял аккаунты без единого членства."""
    user = CustomUser.objects.create_user(
        email="member@archive.test", username="member_archive", password="x", is_active=True
    )
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
    )

    resp = _delete(operator, company)

    assert resp.status_code == 409
    assert "members" in resp.json()["detail"]
    assert CompanyMember.objects.filter(user=user).exists(), "участники обязаны уцелеть при отказе"


def test_refusal_names_every_holder_at_once(operator, company, db):
    """Отказ обязан назвать ВСЁ, что держит: иначе оператор чинит по одному и жмёт снова."""
    from crm.models import Deal, DealStage

    Deal.objects.create(title="Заявка", company=company, stage=DealStage.objects.get(code="DRAFT"))
    user = CustomUser.objects.create_user(
        email="both@archive.test", username="both_archive", password="x", is_active=True
    )
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )

    detail = _delete(operator, company).json()["detail"]

    assert detail.split(":")[0] == "COMPANY_HAS_HISTORY"
    holders = detail.split(":")[1].split(",")
    assert "deals" in holders and "members" in holders


# ── Архив как замена удалению ───────────────────────────────────────────────


def test_archive_requires_a_reason(operator, company):
    resp = _api(operator).post(f"/api/v1/accounts/companies/{company.pk}/archive/", {}, format="json")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "REASON_REQUIRED"
    company.refresh_from_db()
    assert company.is_active is True


def test_archive_writes_a_trace_the_operator_can_find(operator, company):
    from crm.models import ActivityLog

    resp = _api(operator).post(
        f"/api/v1/accounts/companies/{company.pk}/archive/", {"reason": "дубль карточки"}, format="json"
    )

    assert resp.status_code == 200, resp.content
    company.refresh_from_db()
    assert company.is_active is False
    assert company.archived_by_id == operator.pk
    assert company.archived_reason == "дубль карточки"
    assert company.archived_at is not None

    entry = ActivityLog.objects.get(entity_type="company", entity_id=company.pk)
    # Префикс `admin.` — то, по чему «Журнал доступа» отбирает операторские действия.
    assert entry.event_code.startswith("admin."), "иначе запись есть, но оператор её не увидит"
    assert entry.reason == "дубль карточки"


def test_archive_is_reversible(operator, company):
    api = _api(operator)
    api.post(f"/api/v1/accounts/companies/{company.pk}/archive/", {"reason": "ошиблись"}, format="json")

    resp = api.post(f"/api/v1/accounts/companies/{company.pk}/unarchive/", {}, format="json")

    assert resp.status_code == 200, resp.content
    company.refresh_from_db()
    assert company.is_active is True
    assert company.archived_at is None
    assert company.archived_reason == ""


def test_double_archive_is_refused(operator, company):
    api = _api(operator)
    api.post(f"/api/v1/accounts/companies/{company.pk}/archive/", {"reason": "раз"}, format="json")

    resp = api.post(f"/api/v1/accounts/companies/{company.pk}/archive/", {"reason": "два"}, format="json")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "COMPANY_ALREADY_ARCHIVED"


# ── Архив обязан ВЫВОДИТЬ ИЗ ОБОРОТА, а не только красить строку ────────────


@pytest.fixture
def archived_seller(db, operator):
    from accounts.services import archive_company

    seller = Company.objects.create(
        name="Архивный продавец",
        inn="907500010",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    archive_company(seller, operator, reason="ушёл с рынка")
    return seller


def test_archived_seller_disappears_from_the_buyer_picker(archived_seller, db):
    """Инцидент #436 наоборот: компания не должна остаться в подборе, исчезнув из списка."""
    buyer_user = CustomUser.objects.create_user(
        email="picker@archive.test", username="picker_archive", password="x", is_active=True
    )
    buyer = Company.objects.create(
        name="Покупатель пикера",
        inn="907500011",
        verification_status=VerificationStatus.objects.get(code="L2_VERIFIED"),
    )
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    CompanyMember.objects.create(
        user=buyer_user,
        company=buyer,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_buy=True,
    )

    body = _api(buyer_user).get("/api/v1/accounts/companies/suppliers/").json()

    assert all(row["id"] != archived_seller.pk for row in body)


def test_archived_company_is_out_of_the_seller_queryset(archived_seller):
    assert archived_seller.pk not in set(Company.objects.sellers().values_list("id", flat=True))
    assert archived_seller.pk not in set(Company.objects.verified_sellers().values_list("id", flat=True))
    assert archived_seller.pk in set(Company.objects.archived().values_list("id", flat=True))


def test_archived_company_keeps_its_history(operator, db):
    """Архив прячет из оборота, а не из истории: сделки на месте и открываются."""
    from accounts.services import archive_company
    from crm.models import Deal, DealStage

    company = Company.objects.create(name="С историей", inn="907500012")
    deal = Deal.objects.create(title="Старая сделка", company=company, stage=DealStage.objects.get(code="CLOSED_WON"))

    archive_company(company, operator, reason="слияние")

    deal.refresh_from_db()
    assert deal.company_id == company.pk
    assert Deal.objects.filter(company=company).count() == 1


def test_archived_company_is_findable_by_explicit_filter(operator, archived_seller):
    """Odoo: архив находится фильтром «Archived», а не исчезает совсем."""
    default_list = _api(operator).get("/api/v1/accounts/companies/?is_active=true").json()
    rows = default_list["results"] if isinstance(default_list, dict) else default_list
    assert all(row["id"] != archived_seller.pk for row in rows)

    archived_list = _api(operator).get("/api/v1/accounts/companies/?is_active=false").json()
    rows = archived_list["results"] if isinstance(archived_list, dict) else archived_list
    assert any(row["id"] == archived_seller.pk for row in rows)


def test_capability_is_declared_before_the_button_is_drawn(operator, company, db):
    """Salesforce `deletable`: витрина обязана знать заранее, иначе кнопка гарантированно
    упрётся в отказ."""
    from crm.models import Deal, DealStage

    empty = _api(operator).get(f"/api/v1/accounts/companies/{company.pk}/").json()
    assert empty["can_delete"] is True
    assert empty["delete_blocker"] is None

    Deal.objects.create(title="Заявка", company=company, stage=DealStage.objects.get(code="DRAFT"))
    held = _api(operator).get(f"/api/v1/accounts/companies/{company.pk}/").json()
    assert held["can_delete"] is False
    assert held["delete_blocker"].startswith("COMPANY_HAS_HISTORY")


def test_archive_state_is_not_a_form_field(operator, company):
    """Архив — действие со следом, а не поле: обычный PATCH его не ставит (иначе повторилась
    бы дыра «уровень KYC правился обычным Save»)."""
    resp = _api(operator).patch(f"/api/v1/accounts/companies/{company.pk}/", {"is_active": False}, format="json")

    assert resp.status_code == 200
    company.refresh_from_db()
    assert company.is_active is True, "PATCH не выводит компанию из оборота"


def test_narrow_operator_cannot_archive(company, db):
    """Архив — действие администратора (`is_superuser`): носитель SystemRole=ADMIN без
    суперпользователя после M1-ERP-02 — не администратор."""

    viewer = CustomUser.objects.create_user(
        email="narrow@archive.test",
        username="narrow_archive",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
    )

    resp = _api(viewer).post(
        f"/api/v1/accounts/companies/{company.pk}/archive/", {"reason": "не моё дело"}, format="json"
    )

    assert resp.status_code == 403
    company.refresh_from_db()
    assert company.is_active is True


def test_narrow_operator_cannot_delete(company, db):

    viewer = CustomUser.objects.create_user(
        email="narrow2@archive.test",
        username="narrow2_archive",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
    )

    assert _delete(viewer, company).status_code == 403
    assert Company.objects.filter(pk=company.pk).exists()


def test_archived_at_is_a_business_moment_not_a_utc_date(operator, company):
    """Дата архива печатается в журнале — она обязана быть моментом, а не датой из UTC."""
    _api(operator).post(f"/api/v1/accounts/companies/{company.pk}/archive/", {"reason": "проверка"}, format="json")

    company.refresh_from_db()
    assert (timezone.now() - company.archived_at).total_seconds() < 60
