"""D2-0 (B-011): ленты, сделки и журнал шины, которые BFF Платформы читает у ERP, отвечают как обещает выгрузка.

Продолжение `test_openapi_company_conformance.py` (те же опоры). Список операций — из BFF:
`feeds/notifications.py` (уведомления), `feeds/snapshot.py` (сделки, очередь одобрения), `feeds/activity.py` (журнал и
таймлайн), `feeds/search.py` (поиск документов), `bus_journal.py` (журнал шины), `auth.py` (вход, обновление, выход).
Поведение API файл не меняет.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyType
from core.models import Notification
from core.tests.openapi_fixtures import API, conforms, sends
from crm.models import ActivityLog, Deal, DealStage

pytest_plugins = ["core.tests.openapi_fixtures"]  # фикстуры `admin` и `company`
pytestmark = pytest.mark.django_db


@pytest.fixture
def deal(company):
    client_company = Company.objects.create(name="Клиент Контракт", inn="300000111")
    client_company.types.add(CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client"})[0])
    stage = DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "RFQ_OPEN", "sort_order": 10})[0]
    return Deal.objects.create(title="Заявка D2-0", company=client_company, stage=stage)


# --- уведомления -------------------------------------------------------------------------------------------------


def test_notifications_list_and_marks(admin, company, deal):
    for index in range(2):
        Notification.objects.create(
            audience=Notification.AUDIENCE_PLATFORM_ADMIN,
            user=admin.user,
            title=f"Событие {index}",
            message="m",
            event_code="deal.created",
            deal=deal,
        )
    listing = f"{API}notifications/"
    response = admin.get(listing, {"page_size": 200})
    conforms(response, listing, "get", status=200)
    first = response.json()["results"][0]["id"]
    one = admin.patch(f"{listing}{first}/mark_read/")
    conforms(one, f"{listing}{{id}}/mark_read/", "patch", status=200)
    conforms(admin.patch(f"{listing}mark_all_read/"), f"{listing}mark_all_read/", "patch", status=200)
    missing = admin.patch(f"{listing}999999/mark_read/")
    conforms(missing, f"{listing}{{id}}/mark_read/", "patch", status=404)


# --- сделки, таймлайн, журнал, очередь одобрения, поиск документов ------------------------------------------------


def test_deals_list_and_detail(admin, company, deal):
    listing = f"{API}crm/deals/"
    response = admin.get(listing, {"page_size": 100})
    conforms(response, listing, "get", status=200)
    row = response.json()["results"][0]
    # Поля, которые читает BFF (`feeds/numbers.py`, `feeds/search.py`, `feeds/queue.py`).
    assert {"id", "title", "company_name", "stage_code", "created_at"} <= set(row)
    conforms(admin.get(f"{listing}{deal.id}/"), f"{listing}{{id}}/", "get", status=200)


def test_timeline_and_activity_logs(admin, company, deal):
    ActivityLog.objects.create(
        user=admin.user, action="Заявка создана", detail="", event_code="deal.created", deal=deal, entity_type="deal"
    )
    timeline = f"{API}crm/timeline/"
    response = admin.get(timeline, {"deal_id": deal.id, "limit": 10})
    conforms(response, timeline, "get", status=200)
    assert {"id", "timestamp", "event_code", "action", "user_name", "entity_type", "deal_id"} <= set(response.json()[0])
    refused = admin.get(timeline)
    assert refused.json() == {"detail": "TIMELINE_SCOPE_REQUIRED"}
    conforms(refused, timeline, "get", status=400)
    conforms(admin.get(timeline, {"deal_id": 999999}), timeline, "get", status=404)

    logs = f"{API}crm/activity-logs/"
    response = admin.get(logs, {"page_size": 50})
    conforms(response, logs, "get", status=200)
    # BFF (`feeds/activity.py`) читает ещё `deal_id` и `entity_type`, а журнал платформы их не отдаёт — Q-D20-2.
    assert {"id", "timestamp", "event_code", "action", "user_name"} <= set(response.json()["results"][0])


def test_my_approval_queue_and_document_search(admin, company, deal):
    queue = f"{API}crm/quotes/my-approval-queue/"
    conforms(admin.get(queue, {"page_size": 50}), queue, "get", status=200)
    search = f"{API}crm/analytics/search-documents/"
    conforms(admin.get(search, {"q": "КП", "limit": 8}), search, "get", status=200)


# --- журнал шины -------------------------------------------------------------------------------------------------


def test_bus_journal_reads_and_retries(admin, company):
    base = f"{API}integration/bus"
    conforms(admin.get(f"{base}/overview/"), f"{base}/overview/", "get", status=200)
    deliveries = admin.get(f"{base}/deliveries/", {"status": "dead", "limit": 50})
    conforms(deliveries, f"{base}/deliveries/", "get", status=200)
    inbox = admin.get(f"{base}/inbox/", {"errors": "true", "limit": 50})
    conforms(inbox, f"{base}/inbox/", "get", status=200)
    dead = admin.post(f"{base}/deliveries/retry-dead/", {"subscriber": "crm"}, format="json")
    sends(f"{base}/deliveries/retry-dead/", "post", {"subscriber": "crm"})
    conforms(dead, f"{base}/deliveries/retry-dead/", "post", status=200)
    one = admin.post(f"{base}/deliveries/1/retry/")
    conforms(one, f"{base}/deliveries/{{delivery_id}}/retry/", "post", status=200)
    event = admin.post(f"{base}/inbox/7c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5/retry/")
    conforms(event, f"{base}/inbox/{{event_id}}/retry/", "post", status=200)
    bad = admin.post(f"{base}/inbox/not-a-uuid/retry/")
    conforms(bad, f"{base}/inbox/{{event_id}}/retry/", "post", status=400)


# --- вход, обновление, выход -------------------------------------------------------------------------------------


def test_sso_exchange_refresh_and_logout(settings, admin, company):
    from django.core.cache import cache
    from integration.models import CrmUserMapping

    from accounts.tests.test_sso import SSO_SECRET_PRIMARY, make_sso_jwt

    settings.PLATFORM_SSO_SECRET = [SSO_SECRET_PRIMARY]
    settings.PLATFORM_SSO_ENABLED = True
    cache.clear()
    CrmUserMapping.objects.create(crm_user_id=77, user=admin.user)
    anonymous = APIClient()
    exchange = f"{API}auth/sso/exchange/"
    sends(exchange, "post", {"token": "x"})

    ok = anonymous.post(
        exchange, {"token": make_sso_jwt(sub="77", email=admin.user.email, name="Админ Тест")}, format="json"
    )
    conforms(ok, exchange, "post", status=200)
    assert {"access_token", "expires_in"} <= set(ok.json())  # их читает BFF (`auth.py::_connect_erp`)
    refresh_cookie = ok.cookies["refresh_token"].value

    refreshed = APIClient()
    refreshed.cookies["refresh_token"] = refresh_cookie
    again = refreshed.post(f"{API}auth/token/refresh/", {}, format="json")
    conforms(again, f"{API}auth/token/refresh/", "post", status=200)
    assert "access" in again.json()  # его читает BFF (`auth.py::_erp_logout`)

    refused = anonymous.post(exchange, {"token": "not-a-jwt"}, format="json")
    conforms(refused, exchange, "post", status=401)
    missing = anonymous.post(exchange, {}, format="json")
    assert missing.json() == {"detail": "TOKEN_REQUIRED"}
    conforms(missing, exchange, "post", status=401)

    conforms(admin.post(f"{API}auth/logout/", {}, format="json"), f"{API}auth/logout/", "post", status=205)
