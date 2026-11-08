"""FX-4: смена банковских реквизитов — только после подтверждения сотрудником (решение владельца 2026-11-08).

Кабинет подаёт запрос (`PUT /company`), старые реквизиты действуют до решения; сотрудник подтверждает или отклоняет с причиной
(`/api/v1/finance/bank-changes/`). Администраторы и основной контакт получают уведомление по всем каналам, группу `security`
отключить нельзя. В журнале — реальный IP клиента и маска счёта. Гонки — `test_bank_change_race.py`.
"""

import pytest
from django.conf import settings as dj_settings
from django.utils import timezone
from integration.models import CrmClientMapping, CrmContactMapping
from integration.tests import bus_support
from parties.models import Company, Contact
from portal.models import NoticeChannel, NoticeEmailState, PortalNotice, PortalSecurityEvent
from portal.services import notices
from portal.tests.conftest import PortalAPIClient, make_portal_session
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import CompanyMember, CompanyRole, CustomUser, WorkspaceRole
from accounts.testing import make_own_company

pytestmark = pytest.mark.django_db

COMPANY = "/api/portal/v1/company"
LOG = "/api/portal/v1/company/security-log"
DESK = "/api/v1/finance/bank-changes/"
OLD = "р/с 20208000123456789001 в АКИБ Ипотека Банк"
NEW = "р/с 20208000555566667777 в Банке Пример"
NEWER = "р/с 20208000111122223333 в Другом Банке Пример"
PAIR_SECRET = "s" * 32


@pytest.fixture
def people(client_company):
    """Администратор уже есть (`client_contact`); второй администратор, основной контакт и обычный сотрудник."""
    return {
        "admin2": Contact.objects.create(
            company=client_company, name="Admin Two", email="admin2@example.uz", is_admin=True, can_act=True
        ),
        "primary": Contact.objects.create(
            company=client_company, name="Primary", email="primary@example.uz", is_primary=True
        ),
        "regular": Contact.objects.create(
            company=client_company,
            name="Regular",
            email="regular@example.uz",
            can_act=True,
            invited_at=timezone.now(),
        ),
    }


@pytest.fixture
def crm_paired(settings, monkeypatch, client_company, client_contact):
    import integration.bus

    monkeypatch.setattr(integration.bus, "pair_secrets", lambda publisher, subscriber: [PAIR_SECRET])
    CrmClientMapping.objects.create(company=client_company, crm_client_id=42)
    CrmContactMapping.objects.create(contact=client_contact, crm_contact_id=58)
    bus_support.reset()


def _portal(contact):
    session = make_portal_session(contact, contact.company, "magic_link")
    client = PortalAPIClient()
    client.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    return client


def _staff(email, permissions):
    own = Company.objects.filter(name="FX4 Own Co").first() or make_own_company(
        Company.objects.create(name="FX4 Own Co", inn="400400400")
    )
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    role = CompanyRole.objects.create(company=own, name=email, permissions=permissions)
    CompanyMember.objects.create(
        user=user,
        company=own,
        role=WorkspaceRole.objects.get(code="MEMBER"),
        company_roles=[role],
        is_active=True,
        is_primary=True,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def accountant(db):
    return _staff("accountant@own.example", ["finance.payment"])


def _submit(portal_client, value=NEW, **kwargs):
    return portal_client.put(COMPANY, {"bank_details": value}, format="json", **kwargs)


def _pending_id(portal_client):
    return portal_client.get(COMPANY).json()["bank_change_request"]["id"]


# ── Подача: старые реквизиты действуют ───────────────────────────────────────────────────────────────────


def test_change_is_not_applied_until_staff_confirms(portal_client, client_company):
    res = _submit(portal_client)

    assert res.status_code == 200
    body = res.json()
    assert body["bank_details"] == OLD, "старые реквизиты действуют до подтверждения"
    client_company.refresh_from_db()
    assert client_company.bank_details == OLD
    change = body["bank_change_request"]
    assert change["status"] == "pending"
    assert change["new_bank_details"] == NEW
    assert change["decided_at"] is None and change["reject_reason"] is None


def test_non_admin_cannot_submit_a_change(client_company, people):
    res = _submit(_portal(people["regular"]))

    assert res.status_code == 409
    assert res.json() == {"detail": "ADMIN_REQUIRED"}
    client_company.refresh_from_db()
    assert client_company.bank_details == OLD


def test_colleague_sees_status_but_not_the_new_account(portal_client, people):
    _submit(portal_client)

    change = _portal(people["regular"]).get(COMPANY).json()["bank_change_request"]

    assert change["status"] == "pending"
    assert change["new_bank_details"] is None


def test_same_value_creates_no_request(portal_client):
    res = _submit(portal_client, value=OLD)

    assert res.status_code == 200
    assert res.json()["bank_change_request"] is None
    assert not PortalSecurityEvent.objects.exists()


def test_one_active_request_second_is_refused_and_nothing_is_saved(portal_client, client_company):
    assert _submit(portal_client).status_code == 200

    res = portal_client.put(COMPANY, {"bank_details": NEWER, "legal_address": "Новый адрес"}, format="json")

    assert res.status_code == 409
    assert res.json() == {"detail": "BANK_CHANGE_ALREADY_PENDING"}
    client_company.refresh_from_db()
    assert client_company.legal_address != "Новый адрес"
    assert portal_client.get(COMPANY).json()["bank_change_request"]["new_bank_details"] == NEW


def test_other_fields_of_the_same_put_are_saved_at_once(portal_client, client_company):
    res = portal_client.put(COMPANY, {"bank_details": NEW, "legal_address": "Новый адрес"}, format="json")

    assert res.status_code == 200
    client_company.refresh_from_db()
    assert client_company.legal_address == "Новый адрес"
    assert client_company.bank_details == OLD


def test_profile_save_does_not_overwrite_requisites_changed_meanwhile(portal_client, client_company, monkeypatch):
    """Сессия прочла компанию до решения сотрудника: сохранение профиля не возвращает старые реквизиты."""
    import portal.views as views

    def employee_approves_meanwhile(company, data):
        Company.objects.filter(pk=company.pk).update(bank_details=NEW)
        return []

    monkeypatch.setattr(views, "changed_crm_owned_fields", employee_approves_meanwhile)

    assert portal_client.put(COMPANY, {"legal_address": "Адрес"}, format="json").status_code == 200

    client_company.refresh_from_db()
    assert client_company.bank_details == NEW
    assert client_company.legal_address == "Адрес"


def test_contact_cannot_target_another_company(other_contact, client_company, other_company):
    """Компания — только из сессии: чужой `company`/`company_id` в теле игнорируется, запрос у своей компании."""
    other_contact.is_admin = True
    other_contact.save(update_fields=["is_admin"])
    client = _portal(other_contact)

    res = client.put(
        COMPANY, {"bank_details": NEW, "company_id": client_company.pk, "company": client_company.pk}, format="json"
    )

    assert res.status_code == 200
    client_company.refresh_from_db()
    other_company.refresh_from_db()
    assert client_company.bank_details == OLD
    assert PortalSecurityEvent.objects.filter(company=client_company).count() == 0
    assert PortalSecurityEvent.objects.filter(company=other_company).count() == 1


# ── Повторные смены не дают 500 ──────────────────────────────────────────────────────────────────────────


def test_second_change_in_a_row_is_not_a_server_error(portal_client, people):
    """Уведомление без `dedup_key` падало на `portal_notice_contact_dedup_uniq` со второй смены (500)."""
    portal_client.raise_request_exception = False

    first = _submit(portal_client, NEW)
    second = _submit(portal_client, NEWER)

    assert first.status_code == 200
    assert second.status_code < 500, second.status_code


def test_repeated_changes_do_not_fail_and_each_is_notified(portal_client, people, accountant):
    assert _submit(portal_client, NEW).status_code == 200
    accountant.post(f"{DESK}{_pending_id(portal_client)}/reject/", {"reason": "Счёт не подтверждён"}, format="json")

    second = _submit(portal_client, NEWER)

    assert second.status_code == 200, second.content
    keys = list(
        PortalNotice.objects.filter(contact=people["admin2"], kind="bank_requisites_change_requested").values_list(
            "dedup_key", flat=True
        )
    )
    assert len(keys) == 2 and len(set(keys)) == 2, "отдельные запросы — отдельные уведомления"


def test_repeat_of_the_same_delivery_does_not_duplicate(portal_client, client_company, people):
    _submit(portal_client)
    change_id = _pending_id(portal_client)
    before = PortalNotice.objects.count()

    from portal.services import bank_details_change

    bank_details_change.notify_change(
        client_company, kind="bank_requisites_change_requested", request_id=change_id, params={"actor": "x"}
    )

    assert PortalNotice.objects.count() == before


# ── Кто и как получает уведомление ───────────────────────────────────────────────────────────────────────


def test_all_admins_and_primary_are_notified_by_every_channel(
    portal_client, client_company, client_contact, people, crm_paired
):
    """Сам подавший тоже: если сессию администратора увели, он должен узнать. Обычный сотрудник — нет."""
    _submit(portal_client)

    rows = PortalNotice.objects.filter(kind="bank_requisites_change_requested")
    assert {row.contact_id for row in rows} == {client_contact.pk, people["admin2"].pk, people["primary"].pk}
    assert {row.group for row in rows} == {"security"}
    for row in rows:
        assert row.channel == NoticeChannel.EMAIL, row.email_reason
        assert row.email_state == NoticeEmailState.PENDING
    envelope = bus_support.only("contact.security_notice_requested")
    bus_support.assert_matches_contract(envelope)
    assert envelope["data"]["payload"] == {
        "erp_contact_id": client_contact.pk,
        "crm_contact_id": 58,
        "language": "ru",
        "kind": "bank_requisites_change_requested",
    }
    assert envelope["data"]["crm_client_id"] == 42
    assert "2020" not in str(envelope["data"]), "реквизитов в событии нет"


def test_contact_without_email_gets_cabinet_and_telegram(portal_client, client_contact, people, crm_paired):
    client_contact.email = ""
    client_contact.save(update_fields=["email"])

    _submit(portal_client)

    row = PortalNotice.objects.get(contact=client_contact, kind="bank_requisites_change_requested")
    assert row.channel == NoticeChannel.TELEGRAM
    assert bus_support.only("contact.security_notice_requested")["data"]["payload"]["erp_contact_id"] == client_contact.pk


def test_notice_row_is_rendered_in_the_feed(portal_client, client_contact):
    _submit(portal_client)

    items = portal_client.get("/api/portal/v1/notifications").json()["items"]

    assert items[0]["kind"] == "bank_requisites_change_requested"
    assert items[0]["group"] == "security"
    assert items[0]["link"] == "/company"
    assert items[0]["object"]["type"] == "bank_change"


def test_security_group_cannot_be_disabled_in_settings(portal_client, client_contact):
    res = portal_client.patch(
        "/api/portal/v1/notifications/settings",
        {"groups": {"security": {"email": False, "telegram": False, "in_app": False}}},
        format="json",
    )
    assert res.status_code in (200, 422), res.content

    groups = portal_client.get("/api/portal/v1/notifications/settings").json()["groups"]
    assert groups["security"] == {"in_app": True, "email": True, "telegram": True, "required": True}


def test_stored_opt_out_of_security_does_not_apply(portal_client, client_contact, crm_paired):
    client_contact.notification_settings = {"security": {"email": False, "telegram": False, "in_app": False}}
    client_contact.save(update_fields=["notification_settings"])

    _submit(portal_client)

    row = PortalNotice.objects.get(contact=client_contact, kind="bank_requisites_change_requested")
    assert row.channel == NoticeChannel.EMAIL
    assert bus_support.published("contact.security_notice_requested")


def test_decision_notifies_with_its_own_kind_and_reason(portal_client, people, accountant):
    _submit(portal_client)

    accountant.post(f"{DESK}{_pending_id(portal_client)}/reject/", {"reason": "Нет письма банка"}, format="json")

    row = PortalNotice.objects.get(contact=people["admin2"], kind="bank_requisites_change_rejected")
    assert row.params["reason"] == "Нет письма банка"
    assert row.email_state == NoticeEmailState.PENDING


# ── Журнал: реальный IP и маска счёта ────────────────────────────────────────────────────────────────────


def _proxied(settings):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}


def test_journal_has_the_real_client_ip_behind_proxy(portal_client, settings):
    _proxied(settings)

    _submit(portal_client, REMOTE_ADDR="172.18.0.5", HTTP_X_FORWARDED_FOR="203.0.113.7")

    event = PortalSecurityEvent.objects.get(event_type="bank_details_change_requested")
    assert event.ip_address == "203.0.113.7"


def test_forged_forwarded_header_does_not_reach_the_journal(portal_client, settings):
    """Клиент прислал свой X-Forwarded-For: Caddy его заменяет, а доверенным считается только адрес, поставленный прокси."""
    _proxied(settings)

    _submit(portal_client, REMOTE_ADDR="172.18.0.5", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.7")

    event = PortalSecurityEvent.objects.get(event_type="bank_details_change_requested")
    assert event.ip_address == "203.0.113.7"


def test_without_trusted_proxy_the_header_is_ignored(portal_client):
    """NUM_PROXIES=0 (нет прокси): заголовок целиком подделан клиентом."""
    _submit(portal_client, REMOTE_ADDR="198.51.100.4", HTTP_X_FORWARDED_FOR="6.6.6.6")

    assert PortalSecurityEvent.objects.get().ip_address == "198.51.100.4"


def test_malformed_forwarded_header_falls_back_to_remote_addr(portal_client, settings):
    _proxied(settings)

    _submit(portal_client, REMOTE_ADDR="172.18.0.5", HTTP_X_FORWARDED_FOR="not-an-ip")

    assert PortalSecurityEvent.objects.get().ip_address == "172.18.0.5"


def test_client_ip_matches_throttle_identity(rf, settings):
    """Журнал и лимиты видят один адрес: подделка заголовка не обходит лимит и не попадает в журнал."""
    from portal.views import _client_ip
    from rest_framework.throttling import BaseThrottle

    _proxied(settings)
    request = rf.get("/", REMOTE_ADDR="172.18.0.5", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.7")

    assert _client_ip(request) == BaseThrottle().get_ident(request) == "203.0.113.7"


def test_login_throttle_is_not_bypassed_by_forged_header(anon_portal_client, settings):
    """Прокси дописывает настоящий адрес справа: левая часть, какую ни подделай, — тот же счётчик лимита."""
    from django.core.cache import cache

    _proxied(settings)
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {**settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], "portal_login": "2/minute"},
    }
    cache.clear()
    from portal.throttles import PortalLoginRateThrottle

    PortalLoginRateThrottle.THROTTLE_RATES = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    try:
        codes = [
            anon_portal_client.post(
                "/api/portal/v1/auth/telegram",
                {"init_data": "x"},
                format="json",
                HTTP_X_FORWARDED_FOR=f"6.6.6.{n}, 203.0.113.7",
            ).status_code
            for n in range(4)
        ]
    finally:
        del PortalLoginRateThrottle.THROTTLE_RATES
    assert codes[-1] == 429, codes


def test_journal_does_not_keep_the_full_account_number(portal_client, accountant):
    _submit(portal_client)
    accountant.post(f"{DESK}{_pending_id(portal_client)}/approve/", format="json")

    assert PortalSecurityEvent.objects.count() == 2
    for event in PortalSecurityEvent.objects.all():
        assert "20208000555566667777" not in event.details
        assert "20208000123456789001" not in event.details
        assert "7777" in event.details
    for row in PortalNotice.objects.all():
        assert "20208000555566667777" not in str(row.params)


def test_journal_lists_each_stage_for_the_company_admin(portal_client, client_contact, accountant):
    _submit(portal_client)
    accountant.post(f"{DESK}{_pending_id(portal_client)}/approve/", format="json")

    items = portal_client.get(LOG).json()["items"]

    assert [i["event_type"] for i in items] == ["bank_details_changed", "bank_details_change_requested"]
    assert items[1]["actor_name"] == client_contact.name
    assert items[0]["actor_name"] == "Сотрудник", "имя сотрудника клиенту не раскрываем"


# ── Решение сотрудника ───────────────────────────────────────────────────────────────────────────────────


def test_approve_applies_new_requisites_once(portal_client, client_company, accountant):
    _submit(portal_client)
    change_id = _pending_id(portal_client)

    res = accountant.post(f"{DESK}{change_id}/approve/", format="json")

    assert res.status_code == 200, res.content
    assert res.json()["status"] == "approved"
    client_company.refresh_from_db()
    assert client_company.bank_details == NEW
    body = portal_client.get(COMPANY).json()
    assert body["bank_details"] == NEW
    assert body["bank_change_request"]["status"] == "approved"


def test_approve_is_idempotent(portal_client, people, accountant):
    _submit(portal_client)
    change_id = _pending_id(portal_client)
    accountant.post(f"{DESK}{change_id}/approve/", format="json")
    events = PortalSecurityEvent.objects.count()
    rows = PortalNotice.objects.count()

    again = accountant.post(f"{DESK}{change_id}/approve/", format="json")

    assert again.status_code == 200 and again.json()["status"] == "approved"
    assert PortalSecurityEvent.objects.count() == events
    assert PortalNotice.objects.count() == rows


def test_reject_keeps_requisites_and_shows_reason(portal_client, client_company, accountant):
    _submit(portal_client)
    change_id = _pending_id(portal_client)

    res = accountant.post(f"{DESK}{change_id}/reject/", {"reason": "Счёт не подтверждён банком"}, format="json")

    assert res.status_code == 200, res.content
    client_company.refresh_from_db()
    assert client_company.bank_details == OLD
    change = portal_client.get(COMPANY).json()["bank_change_request"]
    assert change["status"] == "rejected" and change["reject_reason"] == "Счёт не подтверждён банком"


def test_reject_needs_a_reason(portal_client, accountant):
    _submit(portal_client)

    res = accountant.post(f"{DESK}{_pending_id(portal_client)}/reject/", {"reason": "   "}, format="json")

    assert res.status_code == 400
    assert portal_client.get(COMPANY).json()["bank_change_request"]["status"] == "pending"


def test_reject_is_idempotent_and_decided_request_cannot_flip(portal_client, accountant):
    _submit(portal_client)
    change_id = _pending_id(portal_client)
    accountant.post(f"{DESK}{change_id}/reject/", {"reason": "Нет"}, format="json")
    events = PortalSecurityEvent.objects.count()

    again = accountant.post(f"{DESK}{change_id}/reject/", {"reason": "Другая"}, format="json")
    flip = accountant.post(f"{DESK}{change_id}/approve/", format="json")

    assert again.status_code == 200 and again.json()["reject_reason"] == "Нет"
    assert flip.status_code == 409 and flip.json() == {"detail": "BANK_CHANGE_NOT_PENDING"}
    assert PortalSecurityEvent.objects.count() == events


def test_after_rejection_a_new_change_can_be_submitted(portal_client, accountant):
    _submit(portal_client)
    accountant.post(f"{DESK}{_pending_id(portal_client)}/reject/", {"reason": "Нет"}, format="json")

    assert _submit(portal_client, NEWER).status_code == 200


def test_archived_company_cannot_be_approved_but_can_be_rejected(portal_client, client_company, accountant):
    _submit(portal_client)
    change_id = _pending_id(portal_client)
    Company.objects.filter(pk=client_company.pk).update(is_active=False, archived_at=timezone.now())

    approve = accountant.post(f"{DESK}{change_id}/approve/", format="json")
    listed = accountant.get(DESK).json()["items"][0]
    reject = accountant.post(f"{DESK}{change_id}/reject/", {"reason": "Компания в архиве"}, format="json")

    assert approve.status_code == 409 and approve.json() == {"detail": "COMPANY_ARCHIVED"}
    assert listed["company_archived"] is True
    assert reject.status_code == 200
    client_company.refresh_from_db()
    assert client_company.bank_details == OLD


def test_requisites_changed_after_submission_block_approval(portal_client, client_company, accountant):
    """Реквизиты поменял сотрудник после подачи: подтверждение не затирает их молча."""
    _submit(portal_client)
    change_id = _pending_id(portal_client)
    Company.objects.filter(pk=client_company.pk).update(bank_details="Правка сотрудника 20208000999900001111")

    listed = accountant.get(DESK).json()["items"][0]
    res = accountant.post(f"{DESK}{change_id}/approve/", format="json")

    assert listed["stale"] is True
    assert res.status_code == 409 and res.json() == {"detail": "BANK_CHANGE_STALE"}
    client_company.refresh_from_db()
    assert client_company.bank_details == "Правка сотрудника 20208000999900001111"


def test_unknown_request_is_404(accountant):
    assert accountant.post(f"{DESK}999999/approve/", format="json").status_code == 404


@pytest.mark.parametrize("action,body", [("approve", None), ("reject", {"reason": "x"})])
def test_decision_requires_finance_payment(portal_client, action, body):
    _submit(portal_client)
    change_id = _pending_id(portal_client)
    for client in (_staff("viewer@own.example", ["finance.view"]), _staff("supply@own.example", ["supply.manage"])):
        res = client.post(f"{DESK}{change_id}/{action}/", body, format="json")
        assert res.status_code == 403 and res.json() == {"detail": "ROLE_NOT_PERMITTED"}


def test_reader_sees_masked_requisites_only(portal_client):
    _submit(portal_client)

    row = _staff("viewer@own.example", ["finance.view"]).get(DESK).json()["items"][0]

    assert row["new_bank_details"] == "•••• 7777"
    assert row["old_bank_details"] == "•••• 9001"


def test_staff_without_finance_cannot_read_the_queue(portal_client):
    _submit(portal_client)

    assert _staff("supply@own.example", ["supply.manage"]).get(DESK).status_code == 403


def test_decider_sees_full_requisites_and_pending_count(portal_client, accountant, client_company):
    _submit(portal_client)

    body = accountant.get(DESK, {"status": "pending"}).json()

    assert body["pending_count"] == 1
    row = body["items"][0]
    assert row["new_bank_details"] == NEW and row["old_bank_details"] == OLD
    assert row["company_name"] == client_company.name and row["requested_ip"]


def test_portal_contact_cannot_call_the_desk(portal_client):
    assert portal_client.post(f"{DESK}1/approve/", format="json").status_code == 401


def test_staff_are_told_about_a_new_request(portal_client, accountant, django_capture_on_commit_callbacks):
    from core.models.notifications import Notification

    with django_capture_on_commit_callbacks(execute=True):
        _submit(portal_client)

    row = Notification.objects.get(user__email="accountant@own.example")
    assert "Банк" not in row.message and "2020" not in row.message


def test_notify_is_scoped_to_given_recipients(client_company, client_contact, people):
    rows = notices.notify(
        "bank_requisites_change_requested",
        company=client_company,
        object_id=1,
        params={},
        link="/company",
        dedup="x",
        contact_ids=[people["primary"].pk],
    )

    assert [row.contact_id for row in rows] == [people["primary"].pk]
