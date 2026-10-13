"""
Лид: площадка маршрутизирует, сделку создаёт принимающая сторона.

Замер 24-08: единственное действие экрана «Лиды» — «Конвертировать в сделку» — у штатного
оператора ВСЕГДА отказывало (`ADMIN_VIEWER_CANNOT_ACT`), а проходило только у
суперпользователя, которому ADR-0001 бизнес-операции запрещает. Экран был отгружен и на 100 %
нефункционален.

Эталон — Salesforce Lead Queue + Take Ownership: входящий лид лежит в очереди ПЛОЩАДКИ,
оператор его квалифицирует и назначает владельцу, а запись в работу берёт принимающая сторона
— она же становится владельцем созданного объекта. Гард «оператор не действует от лица
арендатора» остаётся нетронутым: не хватало второй половины механики, а не разрешения.

Существовавший тест обходил всю развилку — звал сервис напрямую членом компании с явной
`company=`, то есть был бы зелёным при полностью неработающем HTTP-пути.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    OperatorRole,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from crm.models import Lead


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def world(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    verified = VerificationStatus.objects.get(code="L2_VERIFIED")

    company = Company.objects.create(name="Компания лида", inn="907600001", verification_status=verified)
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    member = CustomUser.objects.create_user(
        email="member@lead.test", username="member_lead", password="x", is_active=True
    )
    CompanyMember.objects.create(
        user=member,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_buy=True,
    )

    stranger_company = Company.objects.create(name="Чужая компания", inn="907600002", verification_status=verified)
    stranger = CustomUser.objects.create_user(
        email="stranger@lead.test", username="stranger_lead", password="x", is_active=True
    )
    CompanyMember.objects.create(
        user=stranger,
        company=stranger_company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
    )

    router_role = OperatorRole.objects.create(
        code="LEAD_ROUTER", name="Маршрутизатор", permissions=["leads.view", "leads.route", "companies.view"]
    )
    router = CustomUser.objects.create_user(
        email="router@lead.test",
        username="router_lead",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        operator_role=router_role,
        is_active=True,
    )

    viewer_role = OperatorRole.objects.create(
        code="LEAD_VIEWER", name="Поддержка лидов", permissions=["leads.view", "companies.view"]
    )
    viewer = CustomUser.objects.create_user(
        email="viewer@lead.test",
        username="viewer_lead",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
        operator_role=viewer_role,
        is_active=True,
    )

    lead = Lead.objects.create(
        name="Иван Петров",
        company="ООО Ромашка",
        phone="+998901112233",
        email="ivan@romashka.uz",
        message="Нужны тормозные колодки",
    )
    return {
        "lead": lead,
        "company": company,
        "member": member,
        "stranger": stranger,
        "router": router,
        "viewer": viewer,
    }


def _route(user, world, **payload):
    body = {"company_id": world["company"].pk, "reason": "профиль совпал"}
    body.update(payload)
    return _api(user).post(f"/api/v1/crm/leads/{world['lead'].pk}/route/", body, format="json")


# ── Маршрутизация — работа площадки ─────────────────────────────────────────


def test_staff_operator_can_route_a_lead(world):
    """Тот самый путь, который отказывал ВСЕГДА: штатный оператор без суперправ."""
    assert world["router"].is_superuser is False

    resp = _route(world["router"], world)

    assert resp.status_code == 200, resp.content
    world["lead"].refresh_from_db()
    assert world["lead"].owner_company_id == world["company"].pk
    assert world["lead"].assigned_by_id == world["router"].pk
    assert world["lead"].is_processed is False, "назначение — ещё не обработка: лид ждёт приёма"


def test_routing_writes_a_trace_the_operator_can_find(world):
    from crm.models import ActivityLog

    _route(world["router"], world)

    entry = ActivityLog.objects.get(entity_type="lead", entity_id=world["lead"].pk)
    assert entry.event_code.startswith("admin."), "иначе запись есть, но «Журнал доступа» её не покажет"
    assert entry.reason == "профиль совпал"


def test_routing_requires_a_reason(world):
    resp = _route(world["router"], world, reason="")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "REASON_REQUIRED"


def test_routing_to_a_missing_company_says_so(world):
    """`.first()` молча проглатывал несуществующий id и уводил в резолв по e-mail — оператор
    видел «нет компании клиента» вместо «такой компании нет»."""
    resp = _route(world["router"], world, company_id=999999)

    assert resp.status_code == 400
    assert resp.json()["detail"] == "COMPANY_NOT_FOUND"


def test_routing_to_an_archived_company_is_refused(world, db):
    """Сцепка с архивом: выведенная из оборота компания не должна получать работу."""
    from accounts.services import archive_company

    archive_company(world["company"], world["router"], reason="ушла с рынка")

    resp = _route(world["router"], world)

    assert resp.status_code == 400
    assert resp.json()["detail"] == "COMPANY_ARCHIVED"


def test_view_only_operator_cannot_route(world):
    """Право `leads.route`, а не «оператор вообще»."""
    resp = _route(world["viewer"], world)

    assert resp.status_code == 403
    world["lead"].refresh_from_db()
    assert world["lead"].owner_company_id is None


def test_view_only_operator_cannot_edit_or_delete_a_lead(world):
    """До 24-08 класс стоял на голом `IsPlatformAdmin`: «Поддержка» с одними `*.view` могла
    править и УДАЛЯТЬ лиды. Сырое удаление снято совсем — лид закрывают отклонением."""
    api = _api(world["viewer"])

    assert api.patch(f"/api/v1/crm/leads/{world['lead'].pk}/", {"name": "Правка"}, format="json").status_code == 403
    assert api.delete(f"/api/v1/crm/leads/{world['lead'].pk}/").status_code in (403, 405)
    world["lead"].refresh_from_db()
    assert world["lead"].name == "Иван Петров"


def test_member_cannot_route_a_lead(world):
    """Маршрутизация — работа площадки: арендатор не раздаёт лиды сам себе."""
    resp = _route(world["member"], world)

    assert resp.status_code == 403


# ── Приём — работа арендатора ───────────────────────────────────────────────


def test_claim_creates_a_deal_owned_by_the_company(world):
    from crm.models import Deal

    _route(world["router"], world)

    resp = _api(world["member"]).post(f"/api/v1/crm/leads/{world['lead'].pk}/claim/")

    assert resp.status_code == 201, resp.content
    deal = Deal.objects.get(pk=resp.json()["deal_id"])
    assert deal.company_id == world["company"].pk, "владелец — компания, а не оператор платформы"
    assert deal.manager_id == world["member"].pk
    assert deal.stage.code == "DRAFT"

    world["lead"].refresh_from_db()
    assert world["lead"].converted_deal_id == deal.pk, "связь лид → сделка обязана быть явной"
    assert world["lead"].converted_at is not None
    assert world["lead"].is_processed is True


def test_claim_before_routing_is_refused(world):
    """Лид в очереди площадки арендатору вообще НЕ ВИДЕН — 404, а не «нельзя»: существование
    чужой записи не подтверждаем (тот же приём, что у Salesforce insufficient access).
    Сервисный гард `LEAD_NOT_ROUTED` остаётся вторым рубежом и проверяется прямым вызовом."""
    resp = _api(world["member"]).post(f"/api/v1/crm/leads/{world['lead'].pk}/claim/")
    assert resp.status_code == 404

    from crm.services import claim_lead

    deal, err = claim_lead(world["lead"], world["member"])
    assert deal is None
    assert err == "LEAD_NOT_ROUTED"


def test_a_stranger_cannot_claim_someone_elses_lead(world):
    """IDOR: лид назначен одной компании — взять его в работу может только она. Чужому он не
    виден вовсе (404), а сервисный гард стережёт второй рубеж."""
    _route(world["router"], world)

    resp = _api(world["stranger"]).post(f"/api/v1/crm/leads/{world['lead'].pk}/claim/")
    assert resp.status_code == 404

    from crm.services import claim_lead

    world["lead"].refresh_from_db()
    deal, err = claim_lead(world["lead"], world["stranger"])
    assert deal is None
    assert err == "LEAD_NOT_YOURS"


def test_second_claim_is_refused(world):
    _route(world["router"], world)
    api = _api(world["member"])
    assert api.post(f"/api/v1/crm/leads/{world['lead'].pk}/claim/").status_code == 201

    resp = api.post(f"/api/v1/crm/leads/{world['lead'].pk}/claim/")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "LEAD_ALREADY_PROCESSED"


def test_operator_still_cannot_create_a_deal_from_a_lead(world):
    """ADR-0002 остаётся в силе: гард на конвертации оператором НЕ снят — механика
    изменилась, а не разрешение."""
    _route(world["router"], world)

    resp = _api(world["router"]).post(f"/api/v1/crm/leads/{world['lead'].pk}/claim/")

    assert resp.status_code == 400
    assert resp.json()["detail"] == "ADMIN_VIEWER_CANNOT_ACT"


# ── Отклонение и видимость очереди ──────────────────────────────────────────


def test_reject_closes_the_lead_with_a_reason(world):
    resp = _api(world["router"]).post(
        f"/api/v1/crm/leads/{world['lead'].pk}/reject/", {"reason": "спам"}, format="json"
    )

    assert resp.status_code == 200, resp.content
    world["lead"].refresh_from_db()
    assert world["lead"].is_processed is True
    assert world["lead"].rejection_reason == "спам"
    assert world["lead"].converted_deal_id is None


def test_member_sees_only_leads_routed_to_their_company(world, db):
    other_lead = Lead.objects.create(name="Чужой лид", phone="+998900000000", email="other@x.uz", message="не ваше")
    _route(world["router"], world)

    rows = _api(world["member"]).get("/api/v1/crm/leads/").json()
    items = rows["results"] if isinstance(rows, dict) else rows

    ids = {row["id"] for row in items}
    assert world["lead"].pk in ids
    assert other_lead.pk not in ids, "очередь площадки арендатору не показывается"


def test_operator_sees_the_whole_queue(world, db):
    Lead.objects.create(name="Второй", phone="+998900000001", email="second@x.uz", message="ещё один")

    rows = _api(world["router"]).get("/api/v1/crm/leads/").json()
    items = rows["results"] if isinstance(rows, dict) else rows

    assert len(items) >= 2


def test_similar_leads_are_found_before_routing(world, db):
    """Публичная форма открыта без аутентификации, поэтому дубли ожидаемы по построению:
    показывать их надо ДО назначения, иначе одна заявка уедет в две компании (Odoo
    «Similar Leads»)."""
    from crm.services import find_similar_leads

    twin = Lead.objects.create(name="Иван П.", phone="+998901112233", email="ivan@romashka.uz", message="повтор")

    similar = find_similar_leads(world["lead"])

    assert twin.pk in {item.pk for item in similar}
