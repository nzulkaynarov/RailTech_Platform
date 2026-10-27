"""«Журнал интеграций» шины ERP в Admin Платформы (W13-A2): `/api/v1/integration/bus/*`.

Сводка подписчиков, доставки и DLQ, принятые события с ошибками, повторы (идемпотентно, с записью `admin.bus.*` в журнал)
и право: администратор ERP или сотрудник своей компании с `team.manage` (раздел `admin` каталога, уровень `full`);
без него — 403 и на чтение, и на повтор. Тел событий в ответах нет.
"""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from rt_bus.django.models import Delivery, Inbox, Outbox

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db

BASE = "/api/v1/integration/bus"
EVENT = uuid.UUID("7c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5")
FAILED = uuid.UUID("8d2e3f4a-5b6c-4d7e-9f80-a1b2c3d4e5f6")
QUOTE_SENT = "uz.railtech.erp.quote.sent.v1"


@pytest.fixture
def own_company(settings):
    company = Company.objects.create(name="ООО РельсТех Демо", inn="7700000202")
    company.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0])
    settings.OWN_COMPANY_ID = company.pk
    return company


def _client(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _staff(company, email, permissions=()) -> APIClient:
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    role = CompanyRole.objects.create(company=company, name=f"Роль {email}", permissions=list(permissions))
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "MEMBER", "sort_order": 10})[0],
        company_roles=[role],
        is_primary=True,
        is_active=True,
    )
    return _client(user)


@pytest.fixture
def journal():
    """Событие ERP, доставка которого в CRM ушла в DLQ (404), и событие CRM с упавшей обработкой."""
    now = timezone.now()
    Outbox.objects.create(
        id=EVENT,
        type=QUOTE_SENT,
        source="rt://erp",
        subject="КП-2026-017",
        correlation_id="req-erp-1",
        envelope={"data": {"payload": {"total": "1250000.00"}}},
        created_at=now,
        dispatched_at=now,
    )
    Delivery.objects.create(
        event_id=EVENT,
        event_type=QUOTE_SENT,
        subscriber="crm",
        status="dead",
        attempts=1,
        last_status_code=404,
        last_error="HTTP 404: not found",
        created_at=now,
        updated_at=now,
    )
    Inbox.objects.create(
        event_id=FAILED,
        type="uz.railtech.crm.client.updated.v1",
        source="rt://crm",
        publisher="crm",
        subject="client/7",
        correlation_id="req-crm-2",
        envelope={},
        status="failed",
        attempts=4,
        error="ValueError: company is not known",
        received_at=now,
        updated_at=now,
    )


def test_team_manager_reads_overview_dlq_and_failed_inbox_without_event_bodies(own_company, journal):
    client = _staff(own_company, "admin@railtech.test", ["team.manage"])
    overview = client.get(f"{BASE}/overview/")
    assert overview.status_code == 200, overview.content
    body = overview.json()
    assert (body["service"], body["dlq_size"], body["inbox_failed"]) == ("erp", 1, 1)
    subs = {s["name"]: s for s in body["subscribers"]}
    assert "crm" in subs  # ERP доставляет erp.* подписчикам файла подписок; себе — нет
    assert "erp" not in subs
    assert (subs["crm"]["dead"], subs["crm"]["configured"]) == (1, True)

    dead = client.get(f"{BASE}/deliveries/", {"status": "dead"})
    assert dead.status_code == 200
    [row] = dead.json()["items"]
    assert (row["event_id"], row["subscriber"], row["last_status_code"]) == (str(EVENT), "crm", 404)
    assert (row["subject"], row["correlation_id"]) == ("КП-2026-017", "req-erp-1")
    assert "1250000" not in dead.content.decode()
    assert client.get(f"{BASE}/deliveries/", {"type": "deal.", "subscriber": "crm"}).json() == {
        "items": [],
        "has_more": False,
    }

    inbox = client.get(f"{BASE}/inbox/", {"errors": "true"})
    [entry] = inbox.json()["items"]
    assert (entry["event_id"], entry["status"], entry["error"]) == (
        str(FAILED),
        "failed",
        "ValueError: company is not known",
    )


def test_retries_are_idempotent_and_audited(own_company, journal):
    client = _staff(own_company, "admin@railtech.test", ["team.manage"])
    delivery_id = Delivery.objects.get(event_id=EVENT).pk

    assert client.post(f"{BASE}/deliveries/retry-dead/", {"subscriber": "crm"}, format="json").json() == {"retried": 1}
    assert client.post(f"{BASE}/deliveries/retry-dead/", {"subscriber": "crm"}, format="json").json() == {"retried": 0}
    assert client.post(f"{BASE}/deliveries/{delivery_id}/retry/").json() == {"retried": 1}  # ожидающую — сейчас
    assert client.post(f"{BASE}/deliveries/999999/retry/").json() == {"retried": 0}
    assert Delivery.objects.get(pk=delivery_id).status == "pending"
    assert client.post(f"{BASE}/inbox/{FAILED}/retry/").json() == {"retried": 1}
    assert client.post(f"{BASE}/inbox/{FAILED}/retry/").json() == {"retried": 0}
    assert Inbox.objects.get(pk=FAILED).status == "received"

    codes = list(
        ActivityLog.objects.filter(event_code__startswith="admin.bus.")
        .order_by("id")
        .values_list("event_code", flat=True)
    )
    assert codes == [
        "admin.bus.dead_retried",
        "admin.bus.dead_retried",
        "admin.bus.delivery_retried",
        "admin.bus.delivery_retried",
        "admin.bus.inbox_retried",
        "admin.bus.inbox_retried",
    ]
    first = ActivityLog.objects.filter(event_code="admin.bus.dead_retried").order_by("id").first()
    assert first.user.email == "admin@railtech.test"
    assert first.after_data == {"retried": 1}


def test_superuser_is_allowed(journal, user_factory):
    admin = user_factory(email="root@railtech.test", username="root", is_superuser=True)
    assert _client(admin).get(f"{BASE}/overview/").status_code == 200


def test_staff_without_team_manage_gets_403_on_read_and_retry(own_company, journal):
    client = _staff(own_company, "calc@railtech.test", ["quote.build", "settings.edit"])
    for path in ("/overview/", "/deliveries/", "/inbox/"):
        response = client.get(f"{BASE}{path}")
        assert response.status_code == 403, path
    for path, body in (
        ("/deliveries/1/retry/", None),
        ("/deliveries/retry-dead/", {"subscriber": "crm"}),
        (f"/inbox/{FAILED}/retry/", None),
    ):
        response = client.post(f"{BASE}{path}", body, format="json")
        assert response.status_code == 403, path
    assert Delivery.objects.get(event_id=EVENT).status == "dead"
    assert APIClient().get(f"{BASE}/overview/").status_code == 401


def test_filters_are_validated(own_company):
    client = _staff(own_company, "admin@railtech.test", ["team.manage"])
    for params in ({"status": "lost"}, {"limit": 500}, {"subscriber": "CRM!"}, {"before_id": 0}):
        assert client.get(f"{BASE}/deliveries/", params).status_code == 400, params
    assert client.get(f"{BASE}/inbox/", {"status": "dead"}).status_code == 400
    assert client.post(f"{BASE}/deliveries/retry-dead/", {}, format="json").status_code == 400
    assert client.post(f"{BASE}/inbox/not-a-uuid/retry/").status_code == 400
