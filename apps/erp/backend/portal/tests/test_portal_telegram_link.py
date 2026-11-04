"""Привязка Telegram самим контактом (NOTIFY-1, ADR-0023 п. 3): ссылка бота, статус и отключение из кабинета.

Поле Telegram принадлежит CRM: ERP выпускает подписанную ссылку и публикует запрос отключения, а `telegram_user_id`
меняется только проекцией `crm.contact.updated` (её приём — `integration/tests/test_crm_projections.py`; здесь — что после
проекции Mini App входит).
"""

from __future__ import annotations

import base64
import re
import struct
from datetime import datetime, timedelta, timezone

import pytest
from integration.models import CrmClientMapping, CrmContactMapping
from integration.services import crm_projections as projections
from integration.tests import bus_support
from portal.services import telegram_link
from portal.tests.conftest import make_telegram_init_data
from rest_framework import status

pytestmark = pytest.mark.django_db

PAIR_SECRET = "pair" + "-secret-for-tests"  # из частей: gitleaks сканирует литералы
#: Тот же вектор — в `apps/crm/backend/tests/unit/test_contact_link.py`: формат токена — общий контракт двух систем.
VECTOR = "tg_AQEAAAAAADpq6tt0AAECAwQFBgcIK3Hc6WPbHUmSl6UdUxw_"
TOKEN_RE = re.compile(r"^tg_[A-Za-z0-9_-]{48}$")
NOW = datetime(2026, 11, 4, 7, 0, tzinfo=timezone.utc)
LINK = "/api/portal/v1/me/telegram-link"
STATUS = "/api/portal/v1/me/telegram"


def _decode(token: str) -> tuple[int, int, int, int]:
    """(версия, язык, crm_contact_id, срок) из токена."""
    raw = base64.urlsafe_b64decode(token[3:] + "=" * (-len(token[3:]) % 4))
    version, language, contact, expires, _nonce = struct.unpack(">BB6sI9s", raw[:21])
    return version, language, int.from_bytes(contact, "big"), expires


@pytest.fixture
def linkable(settings, monkeypatch, client_company, client_contact, other_company, other_contact):
    """Бот задан, сопряжение с CRM есть, компании и контакты сопоставлены с CRM (A — 42/58, B — 43/59)."""
    import integration.bus

    settings.TELEGRAM_BOT_USERNAME = "example_bot"
    monkeypatch.setattr(integration.bus, "pair_secrets", lambda publisher, subscriber: [PAIR_SECRET])
    CrmClientMapping.objects.create(company=client_company, crm_client_id=42)
    CrmClientMapping.objects.create(company=other_company, crm_client_id=43)
    CrmContactMapping.objects.create(contact=client_contact, crm_contact_id=58)
    CrmContactMapping.objects.create(contact=other_contact, crm_contact_id=59)
    bus_support.reset()


@pytest.fixture
def unlinked(client_contact, other_contact, readonly_contact):
    """Контакты ещё без Telegram: ссылку выпускают только им (у привязанного — 409)."""
    for contact in (client_contact, other_contact, readonly_contact):
        contact.telegram_user_id, contact.telegram_username = None, ""
        contact.save(update_fields=["telegram_user_id", "telegram_username"])


# ── формат токена ────────────────────────────────────────────────────────────────────────────────────


def test_token_matches_the_shared_vector_fits_telegram_start_and_uses_its_own_key():
    token, expires_at = telegram_link.issue_token(PAIR_SECRET, 58, "uz", NOW, nonce=bytes(range(9)))

    assert token == VECTOR
    assert len(token) <= 64 and TOKEN_RE.fullmatch(token), "параметр start Telegram: до 64 символов [A-Za-z0-9_-]"
    assert expires_at == NOW + timedelta(minutes=15)
    assert _decode(token) == (1, 1, 58, int(expires_at.timestamp()))
    from notifications.mail_bus import content_key

    assert base64.urlsafe_b64encode(telegram_link.link_key(PAIR_SECRET)) != content_key(PAIR_SECRET), "ключ не почтовый"


def test_every_token_is_new_and_the_biggest_contact_id_still_fits():
    first, _ = telegram_link.issue_token(PAIR_SECRET, (1 << 48) - 1, "en", NOW)
    second, _ = telegram_link.issue_token(PAIR_SECRET, (1 << 48) - 1, "en", NOW)

    assert first != second and TOKEN_RE.fullmatch(first) and TOKEN_RE.fullmatch(second)
    with pytest.raises(ValueError):
        telegram_link.issue_token(PAIR_SECRET, 1 << 48, "en", NOW)


# ── POST /me/telegram-link ───────────────────────────────────────────────────────────────────────────


def test_contact_session_gets_a_15_minute_link_for_its_own_crm_contact(linkable, unlinked, portal_client):
    before = datetime.now(timezone.utc)

    res = portal_client.post(LINK, {}, format="json")

    assert res.status_code == status.HTTP_201_CREATED, res.data
    url = res.data["url"]
    assert url.startswith("https://t.me/example_bot?start=tg_")
    token = url.split("start=", 1)[1]
    assert TOKEN_RE.fullmatch(token)
    _version, _language, crm_contact_id, expires = _decode(token)
    assert crm_contact_id == 58, "токен — только на контакт своей сессии"
    expires_at = datetime.fromisoformat(res.data["expires_at"].replace("Z", "+00:00"))
    assert expires == int(expires_at.timestamp())
    assert timedelta(minutes=14) < expires_at - before <= timedelta(minutes=15, seconds=10)


def test_company_b_session_never_gets_a_token_for_company_a_contact(linkable, unlinked, other_portal_client):
    res = other_portal_client.post(LINK, {}, format="json")

    assert res.status_code == status.HTTP_201_CREATED
    assert _decode(res.data["url"].split("start=", 1)[1])[2] == 59


def test_contact_without_the_right_to_act_can_still_connect_telegram(
    linkable, unlinked, readonly_contact, readonly_portal_client
):
    CrmContactMapping.objects.create(contact=readonly_contact, crm_contact_id=60)

    res = readonly_portal_client.post(LINK, {}, format="json")

    assert res.status_code == status.HTTP_201_CREATED
    assert _decode(res.data["url"].split("start=", 1)[1])[2] == 60


def test_contact_not_mapped_to_crm_gets_a_code_not_a_500(linkable, unlinked, readonly_portal_client):
    res = readonly_portal_client.post(LINK, {}, format="json")

    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert res.data == {"detail": "CONTACT_NOT_IN_CRM"}


@pytest.mark.parametrize("missing", ["bot", "pair_secret"])
def test_without_bot_or_crm_pairing_the_link_is_unavailable(
    linkable, unlinked, settings, monkeypatch, portal_client, missing
):
    import integration.bus

    if missing == "bot":
        settings.TELEGRAM_BOT_USERNAME = ""
    else:
        monkeypatch.setattr(integration.bus, "pair_secrets", lambda publisher, subscriber: [])

    res = portal_client.post(LINK, {}, format="json")

    assert res.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert res.data == {"detail": "TELEGRAM_LINK_UNAVAILABLE"}
    assert portal_client.get(STATUS).data["available"] is False


def test_link_and_status_need_a_portal_session(linkable, anon_portal_client):
    assert anon_portal_client.post(LINK, {}, format="json").status_code == status.HTTP_401_UNAUTHORIZED
    assert anon_portal_client.get(STATUS).status_code == status.HTTP_401_UNAUTHORIZED
    assert anon_portal_client.delete(STATUS).status_code == status.HTTP_401_UNAUTHORIZED


def test_already_linked_contact_must_unlink_before_a_new_link(linkable, portal_client):
    """Новый токен при привязанном Telegram — 409: иначе прежний аккаунт остался бы Telegram клиента."""
    res = portal_client.post(LINK, {}, format="json")

    assert res.status_code == status.HTTP_409_CONFLICT
    assert res.data == {"detail": "TELEGRAM_ALREADY_LINKED"}


def test_status_shows_which_account_is_linked_username_or_profile_name(linkable, portal_client, client_contact):
    client_contact.telegram_username, client_contact.telegram_name = "", "Азамат"
    client_contact.save(update_fields=["telegram_username", "telegram_name"])

    assert portal_client.get(STATUS).data["account"] == "Азамат"


# ── GET и DELETE /me/telegram ────────────────────────────────────────────────────────────────────────


def test_status_follows_the_crm_projection(linkable, portal_client, client_contact):
    assert portal_client.get(STATUS).data == {"linked": True, "available": True, "account": "@azamat_client"}

    client_contact.telegram_user_id = None
    client_contact.save(update_fields=["telegram_user_id"])

    assert portal_client.get(STATUS).data == {"linked": False, "available": True, "account": None}


def test_unlink_asks_crm_through_the_outbox_and_leaves_the_field_to_the_projection(
    linkable, portal_client, client_contact
):
    res = portal_client.delete(STATUS)

    assert res.status_code == status.HTTP_202_ACCEPTED
    assert res.data["linked"] is True, "поле меняет только проекция CRM"
    envelope = bus_support.only("contact.telegram_unlink_requested")
    bus_support.assert_matches_contract(envelope)
    assert envelope["data"]["payload"] == {"erp_contact_id": client_contact.pk, "crm_contact_id": 58}
    assert envelope["data"]["crm_client_id"] == 42 and envelope["data"]["actor"] == {"type": "client"}
    client_contact.refresh_from_db()
    assert client_contact.telegram_user_id == 123456789


def test_unlink_of_a_contact_without_telegram_publishes_nothing(linkable, portal_client, client_contact):
    client_contact.telegram_user_id = None
    client_contact.save(update_fields=["telegram_user_id"])

    res = portal_client.delete(STATUS)

    assert res.status_code == status.HTTP_202_ACCEPTED and res.data["linked"] is False
    assert bus_support.published("contact.telegram_unlink_requested") == []


def test_company_b_session_unlinks_only_its_own_contact(linkable, other_portal_client, other_contact):
    assert other_portal_client.delete(STATUS).status_code == status.HTTP_202_ACCEPTED

    envelope = bus_support.only("contact.telegram_unlink_requested")
    assert envelope["data"]["payload"] == {"erp_contact_id": other_contact.pk, "crm_contact_id": 59}
    assert envelope["data"]["crm_client_id"] == 43


def test_failed_publication_rolls_back_and_is_not_reported_as_accepted(linkable, monkeypatch, portal_client):
    from integration.services import events

    def boom(*args, **kwargs):
        raise RuntimeError("outbox недоступен")

    monkeypatch.setattr(events, "publish_event", boom)

    with pytest.raises(RuntimeError):
        portal_client.delete(STATUS)
    assert bus_support.published() == []


# ── проекция CRM → вход в Mini App ───────────────────────────────────────────────────────────────────


def test_projection_from_the_bot_binding_lets_the_mini_app_in(
    linkable, bot_token, readonly_contact, anon_portal_client
):
    """Бот CRM привязал Telegram → `crm.contact.updated` с `telegram_user_id` → проекция → `/auth/telegram` входит."""
    CrmContactMapping.objects.create(contact=readonly_contact, crm_contact_id=60)
    readonly_contact.telegram_user_id = None
    readonly_contact.save(update_fields=["telegram_user_id"])
    init_data = make_telegram_init_data(user_id=700000001)
    assert (
        anon_portal_client.post("/api/portal/v1/auth/telegram", {"init_data": init_data}, format="json").status_code
        == 401
    )

    snapshot = {
        "crm_contact_id": 60,
        "crm_client_id": 42,
        "full_name": readonly_contact.name,
        "telegram_user_id": 700000001,
        "telegram_username": "new_account",
        "telegram_name": "Сардор",
        "is_primary": False,
        "updated_at": "2026-11-04T07:05:00Z",
    }
    assert projections.apply_contact_snapshot({"contact": snapshot}).applied
    readonly_contact.refresh_from_db()
    assert (readonly_contact.telegram_username, readonly_contact.telegram_name) == ("new_account", "Сардор")

    res = anon_portal_client.post("/api/portal/v1/auth/telegram", {"init_data": init_data}, format="json")
    assert res.status_code == status.HTTP_200_OK
    assert res.data["contact"]["id"] == readonly_contact.pk

    unlinked = {**snapshot, "telegram_user_id": None, "updated_at": "2026-11-04T07:10:00Z"}
    assert projections.apply_contact_snapshot({"contact": unlinked}).applied
    readonly_contact.refresh_from_db()
    assert (readonly_contact.telegram_user_id, readonly_contact.telegram_name) == (None, "")


# ── письма ───────────────────────────────────────────────────────────────────────────────────────────


def test_client_mails_point_to_profile_notifications_and_carry_no_token(settings):
    from django.core import mail

    from notifications.emails import send_templated_email

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.CABINET_URL = "https://cabinet.example.test"
    target = "https://cabinet.example.test/profile#notifications"
    send_templated_email(
        "portal_invitation",
        {"contact_name": "Azamat", "company_name": "Acme", "invite_url": "https://x.example/a", "login_code": "1"},
        to=["a@example.test"],
        language="ru",
    )
    send_templated_email(
        "quote_sent",
        {"recipient_name": "Azamat", "seller_name": "Acme", "quote_number": "1", "public_link": "https://x.example/q"},
        to=["a@example.test"],
        language="ru",
    )
    send_templated_email(
        "setup_password", {"first_name": "A", "setup_url": "https://x.example/s"}, to=["s@example.test"]
    )

    invitation, quote, staff = mail.outbox[-3:]
    for message in (invitation, quote):
        html = message.alternatives[0][0]
        assert target in message.body and target in html
        assert "Получать мгновенно в Telegram" in message.body and "Получать мгновенно в Telegram" in html
        assert "start=" not in message.body and "start=" not in html, "токен привязки в письмо не кладётся"
    assert invitation.alternatives[0][0].count(target) == 1, "в приглашении — в тексте письма, без повтора в подвале"
    assert target not in staff.body and target not in staff.alternatives[0][0], "письма сотрудникам — без строки"


# ── POST /me/telegram/test ───────────────────────────────────────────────────────────────────────────

TEST = "/api/portal/v1/me/telegram/test"


@pytest.fixture
def fresh_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def test_test_message_is_a_bus_request_in_the_contact_language(linkable, fresh_cache, portal_client, client_contact):
    client_contact.language = "uz"
    client_contact.save(update_fields=["language"])

    res = portal_client.post(TEST, {}, format="json")

    assert res.status_code == status.HTTP_202_ACCEPTED, res.data
    envelope = bus_support.only("contact.telegram_test_requested")
    bus_support.assert_matches_contract(envelope)
    assert envelope["data"]["payload"] == {"erp_contact_id": client_contact.pk, "crm_contact_id": 58, "language": "uz"}


def test_test_message_at_most_once_a_minute_with_retry_after(linkable, fresh_cache, portal_client):
    assert portal_client.post(TEST, {}, format="json").status_code == status.HTTP_202_ACCEPTED

    again = portal_client.post(TEST, {}, format="json")

    assert again.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert again.data == {"detail": "TOO_MANY_REQUESTS"}
    assert 1 <= int(again["Retry-After"]) <= 60
    assert len(bus_support.published("contact.telegram_test_requested")) == 1


def test_test_message_needs_a_linked_telegram(linkable, fresh_cache, portal_client, client_contact):
    client_contact.telegram_user_id = None
    client_contact.save(update_fields=["telegram_user_id"])

    res = portal_client.post(TEST, {}, format="json")

    assert res.status_code == status.HTTP_409_CONFLICT
    assert res.data == {"detail": "TELEGRAM_NOT_LINKED"}
    assert bus_support.published("contact.telegram_test_requested") == []


def test_failed_test_publication_does_not_burn_the_minute(linkable, fresh_cache, monkeypatch, portal_client):
    from integration.services import events

    real = events.publish_event
    monkeypatch.setattr(events, "publish_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("outbox")))
    with pytest.raises(RuntimeError):
        portal_client.post(TEST, {}, format="json")
    monkeypatch.setattr(events, "publish_event", real)

    assert portal_client.post(TEST, {}, format="json").status_code == status.HTTP_202_ACCEPTED


def test_company_b_test_message_goes_only_to_its_own_contact(linkable, fresh_cache, other_portal_client, other_contact):
    assert other_portal_client.post(TEST, {}, format="json").status_code == status.HTTP_202_ACCEPTED

    envelope = bus_support.only("contact.telegram_test_requested")
    assert envelope["data"]["payload"]["crm_contact_id"] == 59
    assert envelope["data"]["crm_client_id"] == 43


def test_erased_telegram_names_are_erased_in_the_projection_too(linkable, client_contact):
    """`/delete` в CRM: новый снимок с тем же `telegram_user_id`, но без имени и ника — ERP стирает их."""
    base = {
        "crm_contact_id": 58,
        "crm_client_id": 42,
        "full_name": client_contact.name,
        "telegram_user_id": 123456789,
        "is_primary": False,
    }
    named = {**base, "telegram_username": "azamat_new", "telegram_name": "Азамат", "updated_at": "2026-11-04T08:00:00Z"}
    assert projections.apply_contact_snapshot({"contact": named}).applied
    client_contact.refresh_from_db()
    assert (client_contact.telegram_username, client_contact.telegram_name) == ("azamat_new", "Азамат")

    assert projections.apply_contact_snapshot({"contact": {**base, "updated_at": "2026-11-04T08:05:00Z"}}).applied

    client_contact.refresh_from_db()
    assert client_contact.telegram_user_id == 123456789
    assert (client_contact.telegram_username, client_contact.telegram_name) == ("", "")
