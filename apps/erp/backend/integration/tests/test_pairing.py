"""Сопряжение с CRM одним кодом (M3-ERP-05, CONTRACTS §2 «Сопряжение»).

Что проверяется:
1. код: выпуск (хеш в БД, формат), одноразовость, просрочка, неверный код, новый выпуск гасит прежний;
2. приём: секреты в БД шифрованно, аутентификация и подпись вебхуков берут их из БД, `.env` — запасной путь;
3. ротация: два активных токена в переходе, потом старый — 401; повтор той же тройки; ротация из `.env`;
4. утечки: ни кодов, ни секретов в логах (`caplog`) и в ответах статуса;
5. экран ERP «Интеграция с CRM»: статус только для администратора, выпуск кода, аудит без кода;
6. `manage.py pairing_code`.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone
from integration.models import CredentialSlot, IntegrationWebhookEvent, PairingCode, ServiceCredential
from integration.services import credentials, pairing
from integration.services.webhooks import verify_signature_v2, webhook_signing_secret
from integration.tasks import deliver_webhook_event
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

pytestmark = pytest.mark.django_db

PREFIX = "/api/integration/v1"
ENV_TOKEN = "test-service-token"  # conftest._seam_secrets
NEW_CRM_TOKEN = "crm-to-erp-" + "a" * 40
NEW_ERP_TOKEN = "erp-to-crm-" + "b" * 40
NEW_SECRET = "webhook-secret-" + "c" * 40
ROTATED_CRM_TOKEN = "crm-to-erp-" + "d" * 40
ROTATED_ERP_TOKEN = "erp-to-crm-" + "e" * 40
ROTATED_SECRET = "webhook-secret-" + "f" * 40
ALL_VALUES = (NEW_CRM_TOKEN, NEW_ERP_TOKEN, NEW_SECRET, ROTATED_CRM_TOKEN, ROTATED_ERP_TOKEN, ROTATED_SECRET)


def body(crm=NEW_CRM_TOKEN, erp=NEW_ERP_TOKEN, webhook=NEW_SECRET):
    return {"crm_to_erp_token": crm, "erp_to_crm_token": erp, "webhook_secret": webhook}


def bearer(token):
    api = APIClient()
    if token is not None:
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api


def accept(code, **kwargs):
    return bearer(code).post(f"{PREFIX}/pairing/accept", body(**kwargs), format="json")


def rotate(token, **kwargs):
    return bearer(token).post(f"{PREFIX}/pairing/rotate", body(**kwargs), format="json")


def health(token):
    return bearer(token).get(f"{PREFIX}/health").status_code


@pytest.fixture(autouse=True)
def _fresh_undecryptable_log_window(monkeypatch):
    """Окно ограничения лога «нечитаемый секрет» — состояние модуля; каждому тесту — чистое."""
    monkeypatch.setattr("integration.services.credentials._undecryptable_logged_at", {})


@pytest.fixture
def paired():
    code = pairing.issue_code().code
    assert accept(code).status_code == 200
    return code


# ── Код: выпуск, одноразовость, срок ──────────────────────────────────────────────────────────────────


def test_issued_code_is_short_readable_and_only_its_hash_is_stored():
    issued = pairing.issue_code()
    raw = issued.code.replace("-", "")
    assert len(issued.code) == 14 and issued.code.count("-") == 2 and len(raw) == 12
    assert set(raw) <= set(pairing.CODE_ALPHABET), "в коде нет путаемых символов 0/O, 1/I/L"
    row = PairingCode.objects.get()
    assert row.code_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in row.code_hash and raw not in str(row.__dict__)
    assert issued.ttl_seconds == 900
    assert abs((issued.expires_at - timezone.now()).total_seconds() - 900) < 5


def test_new_issue_replaces_the_previous_unused_code():
    first = pairing.issue_code().code
    second = pairing.issue_code().code
    response = accept(first)
    assert response.status_code == 401 and response.json() == {"detail": "PAIRING_CODE_USED"}
    assert accept(second).status_code == 200


def test_code_is_normalized_case_spaces_and_dashes_do_not_matter():
    code = pairing.issue_code().code
    assert accept(code.lower().replace("-", " ")).status_code == 200


# ── Приём: успех и отказы ─────────────────────────────────────────────────────────────────────────────


def test_accept_stores_secrets_encrypted_and_answers_by_contract(settings):
    settings.ERP_VERSION = "9.9.9"
    code = pairing.issue_code().code
    response = accept(code)
    assert response.status_code == 200
    data = response.json()
    assert data["paired"] is True and data["erp_version"] == "9.9.9" and data["paired_at"]
    assert set(data) == {"paired", "paired_at", "erp_version"}
    assert response["Cache-Control"] == "no-store"

    rows = {row.slot: row for row in ServiceCredential.objects.all()}
    assert set(rows) == {CredentialSlot.CRM_TO_ERP, CredentialSlot.ERP_TO_CRM, CredentialSlot.WEBHOOK_SECRET}
    for row, value in (
        (rows["crm_to_erp"], NEW_CRM_TOKEN),
        (rows["erp_to_crm"], NEW_ERP_TOKEN),
        (rows["webhook_secret"], NEW_SECRET),
    ):
        assert value not in row.ciphertext, "в БД шифртекст, не значение"
        assert row.last4 == value[-4:]
    assert credentials.erp_to_crm_token() == NEW_ERP_TOKEN


def test_after_pairing_db_tokens_work_and_env_token_is_ignored():
    assert health(ENV_TOKEN) == 200, "до сопряжения работает токен из .env"
    code = pairing.issue_code().code
    assert accept(code).status_code == 200
    assert health(NEW_CRM_TOKEN) == 200
    assert health(ENV_TOKEN) == 401, ".env — запасной путь только пока в БД пусто"
    assert health("wrong-token") == 401


def test_webhooks_are_signed_with_the_secret_from_db(paired):
    assert webhook_signing_secret() == NEW_SECRET, "секрет из БД перекрывает ERP_WEBHOOK_SECRET из .env"
    event = IntegrationWebhookEvent.objects.create(
        event_type="invite.sent",
        target_url="http://crm.test/events",
        payload={"event": "invite.sent", "occurred_at": timezone.now().isoformat()},
    )
    with patch("httpx.Client.post", return_value=MagicMock(status_code=200, text="OK")) as post:
        assert deliver_webhook_event(event.id) is True
    sent = post.call_args.kwargs
    headers = sent["headers"]
    args = (headers["X-Event-Id"], headers["X-Timestamp"], sent["content"], headers["X-Signature"])
    assert verify_signature_v2(NEW_SECRET, *args)  # подпись v2 (FIX-61) секретом из БД
    assert not verify_signature_v2("test-webhook-secret", *args)


def test_webhook_secret_falls_back_to_env_without_pairing():
    assert webhook_signing_secret() == "test-webhook-secret"


def test_code_cannot_be_used_twice(paired):
    response = accept(paired, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET)
    assert response.status_code == 401
    assert response.json() == {"detail": "PAIRING_CODE_USED"}
    assert health(NEW_CRM_TOKEN) == 200 and health(ROTATED_CRM_TOKEN) == 401, "повтор ничего не переписал"


def test_expired_code_is_rejected():
    code = pairing.issue_code().code
    PairingCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = accept(code)
    assert response.status_code == 401 and response.json() == {"detail": "PAIRING_CODE_EXPIRED"}
    assert not ServiceCredential.objects.exists()


def test_wrong_code_and_missing_code_are_rejected():
    pairing.issue_code()
    for credential in ("ZZZZ-ZZZZ-ZZZZ", "short", None):
        response = accept(credential)
        assert response.status_code == 401, credential
        assert response.json() == {"detail": "PAIRING_CODE_INVALID"}
    assert not ServiceCredential.objects.exists()


def test_service_token_is_not_a_pairing_code():
    pairing.issue_code()
    assert accept(ENV_TOKEN).status_code == 401


def test_non_ascii_bearer_is_401_not_500(paired):
    assert health("t\xe9st-token") == 401
    assert (
        rotate("t\xe9st-token", crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET).status_code == 401
    )


def test_the_code_does_not_authenticate_other_operations():
    code = pairing.issue_code().code
    assert health(code) == 401


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"crm_to_erp_token": NEW_CRM_TOKEN},
        {**body(), "extra": "x"},
        body(crm="short"),
        body(webhook="has spaces " + "x" * 40),
        body(erp=NEW_CRM_TOKEN),
        body(webhook=NEW_CRM_TOKEN),
    ],
    ids=["empty", "missing", "extra-field", "too-short", "bad-alphabet", "same-token-both-ways", "secret-equals-token"],
)
def test_invalid_body_is_422_and_does_not_burn_the_code(payload):
    code = pairing.issue_code().code
    response = bearer(code).post(f"{PREFIX}/pairing/accept", payload, format="json")
    assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}
    assert accept(code).status_code == 200, "код не потрачен на кривое тело"


def test_second_pairing_replaces_everything(paired):
    code = pairing.issue_code().code
    assert accept(code, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET).status_code == 200
    assert health(ROTATED_CRM_TOKEN) == 200
    assert health(NEW_CRM_TOKEN) == 401, "прежние токены гаснут сразу"
    assert webhook_signing_secret() == ROTATED_SECRET


def test_attempts_are_rate_limited(monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "pairing", "3/hour")
    statuses = [accept("ZZZZ-ZZZZ-ZZZZ").status_code for _ in range(4)]
    assert statuses == [401, 401, 401, 429]
    limited = accept("ZZZZ-ZZZZ-ZZZZ")
    assert limited.json() == {"detail": "TOO_MANY_REQUESTS"} and int(limited["Retry-After"]) >= 1


def test_default_pairing_rate_is_set():
    assert SimpleRateThrottle.THROTTLE_RATES["pairing"] == "10/hour"


# ── Ротация без простоя ───────────────────────────────────────────────────────────────────────────────


def test_rotation_keeps_two_tokens_active_then_the_old_one_dies(paired, settings):
    settings.PAIRING_ROTATION_GRACE_SECONDS = 600
    response = rotate(NEW_CRM_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET)
    assert response.status_code == 200
    data = response.json()
    assert data["rotated"] is True and set(data) == {"rotated", "rotated_at", "previous_token_valid_until"}
    assert response["Cache-Control"] == "no-store"
    assert abs((_parse(data["previous_token_valid_until"]) - timezone.now()).total_seconds() - 600) < 5

    assert health(NEW_CRM_TOKEN) == 200, "переход: старый токен ещё работает"
    assert health(ROTATED_CRM_TOKEN) == 200, "и новый тоже"
    assert credentials.erp_to_crm_token() == ROTATED_ERP_TOKEN
    assert webhook_signing_secret() == ROTATED_SECRET, "вебхуки подписываются новым секретом сразу"

    ServiceCredential.objects.filter(slot=CredentialSlot.CRM_TO_ERP_PREVIOUS).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert health(NEW_CRM_TOKEN) == 401, "после перехода старый токен — 401"
    assert health(ROTATED_CRM_TOKEN) == 200
    assert rotate(NEW_CRM_TOKEN, crm="g" * 40, erp="h" * 40, webhook="i" * 40).status_code == 401


def test_rotation_retry_with_the_same_values_is_idempotent(paired):
    first = rotate(NEW_CRM_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET)
    again = rotate(NEW_CRM_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET)
    assert first.status_code == again.status_code == 200
    assert (
        first.json()["previous_token_valid_until"] == again.json()["previous_token_valid_until"]
    ), "срок не продлевается"
    assert health(NEW_CRM_TOKEN) == 200 and health(ROTATED_CRM_TOKEN) == 200


def test_rotation_with_the_current_token_value_is_not_a_rotation(paired):
    response = rotate(NEW_CRM_TOKEN, crm=NEW_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET)
    assert response.status_code == 422 and response.json() == {"detail": "PAIRING_PARTIAL_REPEAT"}
    assert health(NEW_CRM_TOKEN) == 200 and health(ROTATED_CRM_TOKEN) == 401


@pytest.mark.parametrize(
    "kwargs",
    [
        {"erp": NEW_ERP_TOKEN},  # токен ERP→CRM не меняется
        {"webhook": NEW_SECRET},  # секрет вебхуков не меняется
    ],
    ids=["same-erp-to-crm-token", "same-webhook-secret"],
)
def test_rotation_with_an_unchanged_secret_is_422(paired, kwargs):
    values = {"crm": ROTATED_CRM_TOKEN, "erp": ROTATED_ERP_TOKEN, "webhook": ROTATED_SECRET, **kwargs}
    response = rotate(NEW_CRM_TOKEN, **values)
    assert response.status_code == 422 and response.json() == {"detail": "PAIRING_PARTIAL_REPEAT"}
    assert health(ROTATED_CRM_TOKEN) == 401, "отказ ничего не применил"
    assert credentials.webhook_secret() == NEW_SECRET


# ── Контракт шва 0.6.1: полностью новая тройка, точный повтор или PAIRING_PARTIAL_REPEAT ─────────────────


def _stored_values():
    return (
        credentials.stored_crm_token(),
        credentials.erp_to_crm_token(),
        credentials.webhook_secret(),
    )


def test_rotation_with_a_fully_new_triple_is_applied(paired):
    response = rotate(NEW_CRM_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET)
    assert response.status_code == 200
    assert _stored_values() == (ROTATED_CRM_TOKEN, ROTATED_ERP_TOKEN, ROTATED_SECRET)
    # И следующая полностью новая тройка — под новым токеном — тоже применяется.
    third = rotate(ROTATED_CRM_TOKEN, crm="g" * 40, erp="h" * 40, webhook="i" * 40)
    assert third.status_code == 200
    assert _stored_values() == ("g" * 40, "h" * 40, "i" * 40)


def test_exact_repeat_of_the_last_rotation_is_200_and_changes_nothing(paired):
    first = rotate(NEW_CRM_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET)
    before = list(
        ServiceCredential.objects.order_by("slot").values_list("slot", "ciphertext", "rotated_at", "expires_at")
    )
    # Старым токеном (CRM не получила ответ) и новым (CRM уже перешла на него): один и тот же результат.
    for caller in (NEW_CRM_TOKEN, ROTATED_CRM_TOKEN):
        again = rotate(caller, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET)
        assert again.status_code == 200, again.content
        assert again.json() == first.json(), "тот же rotated_at и срок прежнего токена"
    after = list(
        ServiceCredential.objects.order_by("slot").values_list("slot", "ciphertext", "rotated_at", "expires_at")
    )
    assert after == before, "повтор ничего не переписал и не продлил срок"


@pytest.mark.parametrize(
    "same",
    [
        {"crm"},
        {"erp"},
        {"webhook"},
        {"crm", "erp"},
        {"crm", "webhook"},
        {"erp", "webhook"},
    ],
    ids=lambda same: "+".join(sorted(same)),
)
def test_partial_repeat_of_the_last_rotation_is_422(paired, same):
    assert (
        rotate(NEW_CRM_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET).status_code == 200
    )
    stored = _stored_values()
    fresh = {"crm": "g" * 40, "erp": "h" * 40, "webhook": "i" * 40}
    repeated = {"crm": ROTATED_CRM_TOKEN, "erp": ROTATED_ERP_TOKEN, "webhook": ROTATED_SECRET}
    values = {key: repeated[key] if key in same else fresh[key] for key in fresh}
    # И прежним токеном (CRM не знает, дошёл ли первый вызов), и новым.
    for caller in (NEW_CRM_TOKEN, ROTATED_CRM_TOKEN):
        response = rotate(caller, **values)
        assert response.status_code == 422 and response.json() == {"detail": "PAIRING_PARTIAL_REPEAT"}
        assert _stored_values() == stored, "частичный повтор ничего не применил"


@pytest.mark.parametrize("same", [{"crm"}, {"erp"}, {"webhook"}, {"crm", "erp"}, {"erp", "webhook"}])
def test_partial_match_with_the_accepted_values_is_422(paired, same):
    """Частичное совпадение с действующими значениями — и до первой ротации (после приёма кода)."""
    fresh = {"crm": ROTATED_CRM_TOKEN, "erp": ROTATED_ERP_TOKEN, "webhook": ROTATED_SECRET}
    current = {"crm": NEW_CRM_TOKEN, "erp": NEW_ERP_TOKEN, "webhook": NEW_SECRET}
    values = {key: current[key] if key in same else fresh[key] for key in fresh}
    response = rotate(NEW_CRM_TOKEN, **values)
    assert response.status_code == 422 and response.json() == {"detail": "PAIRING_PARTIAL_REPEAT"}
    assert _stored_values() == (NEW_CRM_TOKEN, NEW_ERP_TOKEN, NEW_SECRET)
    assert not ServiceCredential.objects.filter(slot=CredentialSlot.CRM_TO_ERP_PREVIOUS).exists()


def test_the_whole_current_triple_without_a_rotation_is_not_a_rotation(paired):
    response = rotate(NEW_CRM_TOKEN, crm=NEW_CRM_TOKEN, erp=NEW_ERP_TOKEN, webhook=NEW_SECRET)
    assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}
    assert not ServiceCredential.objects.filter(slot=CredentialSlot.CRM_TO_ERP_PREVIOUS).exists()


def test_rotation_with_the_previous_token_value_is_422(paired):
    assert (
        rotate(NEW_CRM_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET).status_code == 200
    )
    # Новое значение токена совпало с переходным прежним: оно ещё действует, ротация другой тройкой — 422.
    response = rotate(ROTATED_CRM_TOKEN, crm=NEW_CRM_TOKEN, erp="j" * 40, webhook="k" * 40)
    assert response.status_code == 422 and response.json() == {"detail": "PAIRING_PARTIAL_REPEAT"}
    assert credentials.webhook_secret() == ROTATED_SECRET


def test_rotation_from_env_with_an_env_secret_is_422(settings):
    settings.ERP_WEBHOOK_SECRET = "env-webhook-secret-" + "z" * 40  # длинный: иначе 422 от формата, не от проверки
    response = rotate(ENV_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=settings.ERP_WEBHOOK_SECRET)
    assert response.status_code == 422 and response.json() == {"detail": "PAIRING_PARTIAL_REPEAT"}
    assert not ServiceCredential.objects.exists()
    assert rotate(ENV_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET).status_code == 200


def test_rotation_needs_the_current_token_not_the_previous_one(paired):
    assert (
        rotate(NEW_CRM_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET).status_code == 200
    )
    again = rotate(NEW_CRM_TOKEN, crm="g" * 40, erp="h" * 40, webhook="i" * 40)
    assert again.status_code == 401, "прежним токеном новую ротацию не начать"
    assert health("g" * 40) == 401


def test_rotation_without_pairing_moves_env_setup_to_the_db():
    assert rotate(ENV_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET).status_code == 200
    assert health(ROTATED_CRM_TOKEN) == 200
    assert health(ENV_TOKEN) == 200, "использованный .env-токен получает тот же переходный срок"
    ServiceCredential.objects.filter(slot=CredentialSlot.CRM_TO_ERP_PREVIOUS).update(expires_at=timezone.now())
    assert health(ENV_TOKEN) == 401


def test_rotation_without_a_valid_token_is_401():
    assert rotate("nope", crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET).status_code == 401
    assert rotate(None).status_code == 401


def test_rotation_with_invalid_body_is_422(paired):
    assert (
        bearer(NEW_CRM_TOKEN).post(f"{PREFIX}/pairing/rotate", {"crm_to_erp_token": "x"}, format="json").status_code
        == 422
    )


# ── Нечитаемые значения ───────────────────────────────────────────────────────────────────────────────


def test_undecryptable_secrets_fall_back_to_env(paired, settings, caplog):
    settings.SECRET_KEY = "another-secret-key-after-rotation-of-django-secret"
    with caplog.at_level(logging.ERROR):
        assert health(ENV_TOKEN) == 200
        assert webhook_signing_secret() == "test-webhook-secret"
    assert health(NEW_CRM_TOKEN) == 401
    assert "undecryptable" in caplog.text
    assert NEW_CRM_TOKEN not in caplog.text


def test_undecryptable_error_is_logged_once_per_window_not_per_request(paired, settings, caplog, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("integration.services.credentials.time.monotonic", lambda: clock["now"])
    monkeypatch.setattr("integration.services.credentials._undecryptable_logged_at", {})
    settings.SECRET_KEY = "another-secret-key-after-rotation-of-django-secret"
    with caplog.at_level(logging.ERROR, logger="integration.services.credentials"):
        for _ in range(5):
            assert health(ENV_TOKEN) == 200
        assert caplog.text.count("undecryptable") == 1, "в одном окне — одна запись, а не по запросу"
        clock["now"] += credentials.UNDECRYPTABLE_LOG_WINDOW_S + 1
        assert health(ENV_TOKEN) == 200
        assert caplog.text.count("undecryptable") == 2, "после окна — снова"


# ── Статус (чтение) ───────────────────────────────────────────────────────────────────────────────────


def test_status_states_none_env_paired(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = []
    settings.ERP_WEBHOOK_SECRET = ""
    assert credentials.status().state == "none"
    settings.SERVICE_TOKEN_CRM_TO_ERP = [ENV_TOKEN]
    settings.ERP_WEBHOOK_SECRET = "test-webhook-secret"
    status = credentials.status()
    assert status.state == "env" and status.webhook_secret_source == "env"
    assert status.crm_to_erp_last4 == "" and status.webhook_secret_last4 == "", "значения .env на экран не выводятся"
    code = pairing.issue_code().code
    assert accept(code).status_code == 200
    status = credentials.status()
    assert status.state == "paired" and status.token_source == "db" and status.paired_at
    assert status.crm_to_erp_last4 == NEW_CRM_TOKEN[-4:] and status.webhook_secret_last4 == NEW_SECRET[-4:]
    assert status.erp_to_crm_configured and status.rotated_at is None and status.previous_token_valid_until is None


def test_status_shows_rotation_window(paired):
    rotate(NEW_CRM_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET)
    status = credentials.status()
    assert status.rotated_at and status.previous_token_valid_until and status.crm_to_erp_last4 == ROTATED_CRM_TOKEN[-4:]


# ── Утечки ────────────────────────────────────────────────────────────────────────────────────────────


def test_no_code_and_no_secret_reaches_logs_or_responses(caplog, settings):
    settings.PAIRING_ROTATION_GRACE_SECONDS = 600
    with caplog.at_level(logging.DEBUG):
        issued = pairing.issue_code()
        raw = issued.code.replace("-", "")
        responses = [
            accept("ZZZZ-ZZZZ-ZZZZ"),
            accept(issued.code),
            accept(issued.code),
            rotate(NEW_CRM_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET),
            rotate("wrong"),
            bearer(NEW_CRM_TOKEN).get(f"{PREFIX}/health"),
        ]
    text = caplog.text + "".join(r.content.decode() for r in responses)
    for secret in (*ALL_VALUES, raw, issued.code, "ZZZZ-ZZZZ-ZZZZ"):
        assert secret not in text, f"утечка в логах или ответах: {secret[:6]}…"


# ── Экран ERP «Интеграция с CRM» ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_api(user_factory):
    from rest_framework_simplejwt.tokens import RefreshToken

    user = user_factory(email="admin@example.com", username="admin", is_staff=True, is_superuser=True)
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return api, user


STATUS_URL = "/api/v1/integration/crm-pairing/"
CODE_URL = "/api/v1/integration/crm-pairing/code/"


def test_screen_endpoints_are_for_superuser_only(authenticated_client):
    assert authenticated_client.get(STATUS_URL).status_code == 403
    assert authenticated_client.post(CODE_URL).status_code == 403
    assert APIClient().get(STATUS_URL).status_code == 401
    assert APIClient().post(CODE_URL).status_code == 401
    assert not PairingCode.objects.exists()


def test_superuser_issues_a_code_that_pairs_and_the_audit_has_no_code(admin_api):
    api, user = admin_api
    response = api.post(CODE_URL)
    assert response.status_code == 200 and response["Cache-Control"] == "no-store"
    data = response.json()
    assert data["ttl_seconds"] == 900 and len(data["code"]) == 14
    assert PairingCode.objects.get().created_by == user
    assert accept(data["code"]).status_code == 200

    from crm.models import ActivityLog

    entry = ActivityLog.objects.get(entity_type="crm_pairing", event_code="integration.pairing_code_issued")
    assert entry.user == user
    assert data["code"] not in f"{entry.action} {entry.detail} {entry.before_data} {entry.after_data}"


def test_status_endpoint_never_returns_secret_values(admin_api):
    api, _ = admin_api
    before = api.get(STATUS_URL).json()
    assert before["state"] == "env" and before["token_source"] == "env" and before["paired_at"] is None
    assert before["code_ttl_seconds"] == 900
    assert accept(api.post(CODE_URL).json()["code"]).status_code == 200
    rotate(NEW_CRM_TOKEN, crm=ROTATED_CRM_TOKEN, erp=ROTATED_ERP_TOKEN, webhook=ROTATED_SECRET)
    response = api.get(STATUS_URL)
    after = response.json()
    assert after["state"] == "paired" and after["rotated_at"] and after["previous_token_valid_until"]
    assert after["crm_to_erp_last4"] == ROTATED_CRM_TOKEN[-4:] and after["erp_to_crm_configured"] is True
    for secret in ALL_VALUES:
        assert secret not in response.content.decode()


# ── manage.py pairing_code ────────────────────────────────────────────────────────────────────────────


def test_management_command_prints_a_working_code_once():
    out = io.StringIO()
    call_command("pairing_code", stdout=out)
    printed = out.getvalue()
    code = next(line.split(": ", 1)[1] for line in printed.splitlines() if line.startswith("Код сопряжения"))
    assert PairingCode.objects.get().created_by is None
    assert code not in PairingCode.objects.get().code_hash
    assert accept(code).status_code == 200


def _parse(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))
