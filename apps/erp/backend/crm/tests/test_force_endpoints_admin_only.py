"""FIX-43 (F-10): аварийные эндпоинты оператора — только администратору, с причиной и следом.

`force-approve` (КП), `force-cancel` (договор), `force-change-stage` (сделка) обходят конечные автоматы
статусов. Решение владельца «по рекомендации» (docs/DECISIONS.md, FIX-43): оставить, но ТОЛЬКО администратору
ERP (`is_superuser`), с обязательной непустой строкой-причиной и записью в журнал (`ActivityLog` через
`log_admin_action`: кто, зачем, было → стало). Роль в компании, даже «Руководитель» со всеми правами, и
устаревшая системная роль ADMIN без `is_superuser` — не администратор.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import ActivityLog, Contract, ContractStatus, Deal, DealStage, Quote, QuoteStatus
from master_data.models import Country

ENDPOINTS = ("quote", "contract", "deal")


@pytest.fixture
def scene(db):
    for code in ["DRAFT", "SOURCING", "CALCULATING", "QUOTE_SENT", "CLOSED_LOST"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "SENT", "APPROVED"]:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "SIGNED", "CANCELLED"]:
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    country = Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})[0]
    buyer = Company.objects.create(name="Force Buyer", inn="430000001")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    seller = Company.objects.create(name="Force Seller", inn="430000002")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    deal = Deal.objects.create(title="Force deal", company=buyer, stage=DealStage.objects.get(code="CALCULATING"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        seller_company=seller,
        tax_country=country,
        vat_rate=Decimal("12.00"),
        total_incl_vat=Decimal("112.00"),
    )
    contract = Contract.objects.create(
        deal=deal, quote=quote, number="CT-FORCE-1", status=ContractStatus.objects.get(code="SIGNED")
    )
    return {"seller": seller, "deal": deal, "quote": quote, "contract": contract}


def _user(email, **extra):
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True, **extra)


@pytest.fixture
def admin(scene):
    return _user("force.admin@example.test", is_staff=True, is_superuser=True)


@pytest.fixture
def head(scene, grant):
    """Руководитель своей компании: все права ролей бэк-офиса, но не администратор ERP."""
    user = _user("force.head@example.test", is_staff=True)
    CompanyMember.objects.create(
        user=user,
        company=scene["seller"],
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_primary=True,
        is_active=True,
        can_sell=True,
    )
    grant(user, "HEAD")
    return user


@pytest.fixture
def legacy_admin(scene):
    """Системная роль ADMIN без `is_superuser` — «администратором» больше не считается."""
    role = SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 10})[0]
    return _user("force.legacy@example.test", is_staff=True, role=role)


@pytest.fixture
def plain(scene):
    return _user("force.plain@example.test")


def _client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def _target(scene, kind):
    """(url, body без причины, event_code следа, текущее состояние, функция чтения состояния)."""
    if kind == "quote":
        obj = scene["quote"]
        return (
            f"/api/v1/crm/quotes/{obj.pk}/force-approve/",
            {},
            "quote.approved_force",
            "SENT",
            lambda: Quote.objects.get(pk=obj.pk).status.code,
        )
    if kind == "contract":
        obj = scene["contract"]
        return (
            f"/api/v1/crm/contracts/{obj.pk}/force-cancel/",
            {},
            "contract.cancelled_force",
            "SIGNED",
            lambda: Contract.objects.get(pk=obj.pk).status.code,
        )
    obj = scene["deal"]
    return (
        f"/api/v1/crm/deals/{obj.pk}/force-change-stage/",
        {"stage_code": "CLOSED_LOST"},
        "deal.stage_changed_force",
        "CALCULATING",
        lambda: Deal.objects.get(pk=obj.pk).stage.code,
    )


def _force_logs(event_code):
    return ActivityLog.objects.filter(event_code=event_code)


# ── Матрица ролей: кроме администратора ERP не может никто ───────────────────


@pytest.mark.parametrize("kind", ENDPOINTS)
def test_anonymous_gets_401_and_nothing_changes(scene, kind):
    url, body, event, before, read = _target(scene, kind)

    resp = _client().post(url, {**body, "reason": "нужно"}, format="json")

    assert resp.status_code == 401
    assert read() == before
    assert not _force_logs(event).exists()


@pytest.mark.parametrize("who", ["head", "legacy_admin", "plain"])
@pytest.mark.parametrize("kind", ENDPOINTS)
def test_everyone_but_the_erp_admin_is_refused_by_code(scene, request, who, kind):
    """Руководитель компании, «админ» по устаревшей системной роли и рядовой пользователь — 403
    `PLATFORM_ADMIN_REQUIRED`, статус не меняется, следа нет (даже с причиной)."""
    user = request.getfixturevalue(who)
    url, body, event, before, read = _target(scene, kind)

    resp = _client(user).post(url, {**body, "reason": "очень нужно"}, format="json")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "PLATFORM_ADMIN_REQUIRED"
    assert read() == before
    assert not _force_logs(event).exists()


# ── Причина обязательна ──────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [None, "", "   ", "\n\t", 123, ["x"], {"a": 1}, True])
@pytest.mark.parametrize("kind", ENDPOINTS)
def test_admin_without_a_real_reason_gets_400_not_500(scene, admin, kind, bad):
    """Пустая, из пробелов или не строковая причина — отказ 400 с кодом, не падение 500."""
    url, body, event, before, read = _target(scene, kind)

    resp = _client(admin).post(url, {**body, "reason": bad}, format="json")

    assert resp.status_code == 400
    assert resp.json()["detail"] in {"FORCE_REASON_REQUIRED", "REASON_REQUIRED"}
    assert read() == before
    assert not _force_logs(event).exists()


@pytest.mark.parametrize("kind", ENDPOINTS)
def test_admin_without_the_reason_field_at_all_gets_400(scene, admin, kind):
    url, body, event, before, read = _target(scene, kind)

    resp = _client(admin).post(url, body, format="json")

    assert resp.status_code == 400
    assert read() == before
    assert not _force_logs(event).exists()


# ── Администратор с причиной: действие выполняется и остаётся в журнале ──────


@pytest.mark.parametrize(
    "kind, after",
    [("quote", "APPROVED"), ("contract", "CANCELLED"), ("deal", "CLOSED_LOST")],
)
def test_admin_with_a_reason_acts_and_leaves_a_trace(scene, admin, kind, after):
    url, body, event, before, read = _target(scene, kind)

    resp = _client(admin).post(url, {**body, "reason": "  Эскалация INC-43  "}, format="json")

    assert resp.status_code == 200, resp.content
    assert read() == after
    entry = _force_logs(event).get()
    assert entry.user_id == admin.pk
    assert entry.reason.strip() == "Эскалация INC-43"
    assert entry.level == "WARNING"
    assert entry.entity_id is not None
    assert list(entry.before_data.values())[0] == before
    assert list(entry.after_data.values())[0] == after


def test_force_cancel_keeps_the_reason_and_admin_email_out_of_the_client_facing_notes(scene, admin):
    """`contract.notes` печатается в PDF договора для клиента: причина и e-mail администратора — только в журнале."""
    contract = scene["contract"]
    contract.notes = "Условия клиента"
    contract.save(update_fields=["notes"])

    resp = _client(admin).post(
        f"/api/v1/crm/contracts/{contract.pk}/force-cancel/", {"reason": "Внутренний инцидент"}, format="json"
    )

    assert resp.status_code == 200
    contract.refresh_from_db()
    assert contract.notes == "Условия клиента"
    assert admin.email not in contract.notes and "Внутренний инцидент" not in contract.notes
    assert _force_logs("contract.cancelled_force").get().reason == "Внутренний инцидент"


def test_force_cancel_by_a_non_superuser_with_the_admin_role_is_refused_at_service_level(scene, legacy_admin):
    """Сервис — вторая линия: его зовут не только из вьюхи. Роль ADMIN без `is_superuser` не проходит."""
    from crm.services import force_cancel_contract

    contract, err = force_cancel_contract(scene["contract"].pk, legacy_admin, reason="попытка")

    assert contract is None
    assert err == "PLATFORM_ADMIN_REQUIRED"
    assert Contract.objects.get(pk=scene["contract"].pk).status.code == "SIGNED"
    assert not _force_logs("contract.cancelled_force").exists()


def test_service_level_force_approve_refuses_a_non_string_reason(scene, admin):
    from crm.services.quotes import QuoteLifecycleService

    quote, err = QuoteLifecycleService.force_approve_quote(scene["quote"].pk, admin, reason=123)

    assert quote is None
    assert err == "FORCE_REASON_REQUIRED"
