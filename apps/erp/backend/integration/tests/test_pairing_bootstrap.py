"""Первое сопряжение без кода — bootstrap (M3-ERP-05, CONTRACTS §2, ADR-0009).

Каждая ветка: успех; повтор `jti`; старая и будущая метка; неверный ключ; подмена тела; кривой заголовок; нет общего
секрета; отказ после сопряжения; отказ после очистки токенов (флаг переживает); код из ERP работает; ключ выводится с
меткой (не сам SSO-секрет); ни доказательств, ни секретов в логах и ответах.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

import pytest
from integration.models import PairingState, ServiceCredential
from integration.services import bootstrap, credentials, pairing
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

URL = "/api/integration/v1/pairing/accept"
SSO_SECRET = "test-sso-secret"  # conftest._seam_secrets
ENV_TOKEN = "test-service-token"
SECRETS = {
    "crm_to_erp_token": "boot-crm-to-erp-" + "a" * 40,
    "erp_to_crm_token": "boot-erp-to-crm-" + "b" * 40,
    "webhook_secret": "boot-webhook-secret-" + "c" * 40,
}


def raw(body=None) -> bytes:
    return json.dumps(SECRETS if body is None else body, separators=(",", ":")).encode()


def proof_for(body: bytes, *, secret=SSO_SECRET, ts=None, jti=None) -> str:
    return bootstrap.sign(secret, body, int(time.time()) if ts is None else ts, jti or uuid.uuid4().hex)


def post(body: bytes | None = None, proof: str | None = None, *, authorization: str | None = None):
    body = raw() if body is None else body
    headers = {}
    if proof is not None:
        headers["HTTP_X_PAIRING_PROOF"] = proof
    if authorization is not None:
        headers["HTTP_AUTHORIZATION"] = authorization
    return APIClient().post(URL, data=body, content_type="application/json", **headers)


def bootstrap_ok():
    body = raw()
    return post(body, proof_for(body))


# ── Успех ─────────────────────────────────────────────────────────────────────────────────────────────


def test_bootstrap_pairs_an_unpaired_erp_and_closes_the_window(settings):
    settings.ERP_VERSION = "7.7.7"
    assert pairing.bootstrap_is_open()
    response = bootstrap_ok()
    assert response.status_code == 200
    data = response.json()
    assert (
        data["paired"] is True
        and data["erp_version"] == "7.7.7"
        and set(data) == {"paired", "paired_at", "erp_version"}
    )
    assert response["Cache-Control"] == "no-store"
    assert credentials.stored_crm_token() == SECRETS["crm_to_erp_token"]
    assert credentials.erp_to_crm_token() == SECRETS["erp_to_crm_token"]
    assert credentials.webhook_secret() == SECRETS["webhook_secret"]
    assert PairingState.objects.get(pk=1).bootstrap_used_at is not None
    assert not pairing.bootstrap_is_open()
    # Токены из БД работают, токен из `.env` больше нет.
    ok = APIClient()
    ok.credentials(HTTP_AUTHORIZATION=f"Bearer {SECRETS['crm_to_erp_token']}")
    assert ok.get("/api/integration/v1/health").status_code == 200
    old = APIClient()
    old.credentials(HTTP_AUTHORIZATION=f"Bearer {ENV_TOKEN}")
    assert old.get("/api/integration/v1/health").status_code == 401


def test_bootstrap_is_audited_without_secrets_and_the_code_path_too():
    from crm.models import ActivityLog

    body = raw()
    header = proof_for(body)
    assert post(body, header).status_code == 200
    entry = ActivityLog.objects.get(entity_type="crm_pairing", event_code="integration.paired_bootstrap")
    assert entry.user is None and entry.after_data["method"] == "bootstrap"
    dump = f"{entry.action} {entry.detail} {entry.after_data} {entry.before_data}"
    for secret in (*SECRETS.values(), header, SSO_SECRET):
        assert secret not in dump
    code = pairing.issue_code().code
    assert post(raw(), authorization=f"Bearer {code}").status_code == 200
    assert ActivityLog.objects.filter(event_code="integration.paired_code").exists()


def test_bootstrap_works_with_any_active_sso_secret_during_rotation(settings):
    settings.PLATFORM_SSO_SECRET = ["new-sso-secret-for-rotation", SSO_SECRET]
    body = raw()
    assert post(body, proof_for(body, secret=SSO_SECRET)).status_code == 200


# ── Отказы доказательства ─────────────────────────────────────────────────────────────────────────────


def test_replayed_jti_is_rejected():
    body = raw()
    jti = uuid.uuid4().hex
    first = proof_for(body, jti=jti)
    # Первый вызов с телом, которое ERP не примет (422), всё равно сжигает jti: повтор — отказ.
    bad = raw({"crm_to_erp_token": "short"})
    assert post(bad, proof_for(bad, jti=jti)).status_code == 422
    response = post(body, first)
    assert response.status_code == 401 and response.json() == {"detail": "PAIRING_PROOF_REPLAYED"}
    assert not ServiceCredential.objects.exists()


@pytest.mark.parametrize("shift", [-301, -3600, 301, 3600])
def test_stale_or_future_timestamp_is_expired(shift):
    body = raw()
    response = post(body, proof_for(body, ts=int(time.time()) + shift))
    assert response.status_code == 401 and response.json() == {"detail": "PAIRING_PROOF_EXPIRED"}
    assert not ServiceCredential.objects.exists()


def test_timestamp_edge_of_the_window_is_accepted():
    body = raw()
    assert post(body, proof_for(body, ts=int(time.time()) - 290)).status_code == 200


def test_wrong_key_is_invalid():
    body = raw()
    response = post(body, proof_for(body, secret="some-other-sso-secret"))
    assert response.status_code == 401 and response.json() == {"detail": "PAIRING_PROOF_INVALID"}
    assert not ServiceCredential.objects.exists() and pairing.bootstrap_is_open()


def test_the_sso_secret_itself_is_not_the_key():
    """Ключ — отдельный, с меткой: подпись, посчитанная прямо SSO-секретом, не принимается."""
    import hashlib
    import hmac

    body, ts, jti = raw(), int(time.time()), uuid.uuid4().hex
    message = f"{ts}.{jti}.{hashlib.sha256(body).hexdigest()}"
    direct = hmac.new(SSO_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    assert post(body, f"v1.{ts}.{jti}.{direct}").json() == {"detail": "PAIRING_PROOF_INVALID"}
    assert bootstrap.derive_key(SSO_SECRET) != SSO_SECRET.encode()


def test_tampered_body_is_invalid():
    body = raw()
    header = proof_for(body)
    other = raw({**SECRETS, "webhook_secret": "attacker-webhook-secret-" + "z" * 30})
    assert post(other, header).json() == {"detail": "PAIRING_PROOF_INVALID"}
    assert not ServiceCredential.objects.exists()


@pytest.mark.parametrize(
    "header",
    [
        "",
        "garbage",
        "v2.1.abcdefabcdefabcdef.deadbeef",
        "v1.notanumber.0123456789abcdef.00",
        "v1.1.short." + "0" * 64,
        "v1.1.2.3.4",
    ],
)
def test_malformed_headers_are_invalid(header):
    assert post(raw(), header).status_code == 401
    assert not ServiceCredential.objects.exists()


def test_no_shared_secret_means_bootstrap_is_unavailable(settings):
    settings.PLATFORM_SSO_SECRET = []
    body = raw()
    assert post(body, proof_for(body)).json() == {"detail": "PAIRING_PROOF_INVALID"}


def test_invalid_body_with_valid_proof_is_422_and_window_stays_open():
    body = raw({"crm_to_erp_token": "short"})
    assert post(body, proof_for(body)).status_code == 422
    assert pairing.bootstrap_is_open()


# ── Окно закрывается навсегда ─────────────────────────────────────────────────────────────────────────


def test_bootstrap_after_pairing_is_409_not_a_second_pairing():
    assert bootstrap_ok().status_code == 200
    body = raw({**SECRETS, "crm_to_erp_token": "attacker-token-" + "q" * 40})
    response = post(body, proof_for(body))
    assert response.status_code == 409 and response.json() == {"detail": "BOOTSTRAP_CLOSED"}
    assert credentials.stored_crm_token() == SECRETS["crm_to_erp_token"], "ничего не перезаписано"


def test_forged_proof_after_pairing_is_401_not_409():
    """409 видит только тот, кто доказал владение секретом: подделка не узнаёт состояние ERP."""
    assert bootstrap_ok().status_code == 200
    body = raw()
    assert post(body, proof_for(body, secret="wrong")).status_code == 401


def test_bootstrap_stays_closed_after_the_tokens_are_wiped():
    assert bootstrap_ok().status_code == 200
    ServiceCredential.objects.all().delete()  # админ ERP «вернулся на .env»
    assert credentials.status().state == "env"
    body = raw()
    response = post(body, proof_for(body))
    assert response.status_code == 409 and response.json() == {"detail": "BOOTSTRAP_CLOSED"}


def test_pairing_by_code_closes_the_window_too():
    code = pairing.issue_code().code
    response = post(raw(), authorization=f"Bearer {code}")
    assert response.status_code == 200
    body = raw()
    assert post(body, proof_for(body)).json() == {"detail": "BOOTSTRAP_CLOSED"}


def test_rotation_from_env_closes_the_window_too():
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {ENV_TOKEN}")
    assert api.post("/api/integration/v1/pairing/rotate", SECRETS, format="json").status_code == 200
    body = raw()
    assert post(body, proof_for(body)).json() == {"detail": "BOOTSTRAP_CLOSED"}


def test_code_from_erp_still_works_after_bootstrap_and_replaces_keys():
    assert bootstrap_ok().status_code == 200
    code = pairing.issue_code().code
    renewed = {
        "crm_to_erp_token": "renewed-crm-to-erp-" + "d" * 40,
        "erp_to_crm_token": "renewed-erp-to-crm-" + "e" * 40,
        "webhook_secret": "renewed-webhook-" + "f" * 40,
    }
    response = post(raw(renewed), authorization=f"Bearer {code}")
    assert response.status_code == 200
    assert credentials.stored_crm_token() == renewed["crm_to_erp_token"]


def test_a_code_header_without_proof_is_still_the_code_path():
    assert post(raw(), authorization="Bearer ZZZZ-ZZZZ-ZZZZ").json() == {"detail": "PAIRING_CODE_INVALID"}


def test_attempts_are_rate_limited(monkeypatch):
    from rest_framework.throttling import SimpleRateThrottle

    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "pairing", "2/hour")
    body = raw()
    statuses = [post(body, proof_for(body, secret="wrong")).status_code for _ in range(3)]
    assert statuses == [401, 401, 429]


# ── Тест-вектор контракта и утечки ────────────────────────────────────────────────────────────────────


def _vector() -> dict:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "contracts" / "examples" / "pairing-bootstrap.json"
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    pytest.fail(
        "packages/contracts/examples/pairing-bootstrap.json не найден (монтирование /packages/contracts)", pytrace=False
    )


def test_contract_test_vector_matches_the_implementation():
    vector = _vector()
    body = vector["body"].encode()
    assert vector["label"].encode() == bootstrap.LABEL
    assert bootstrap.sign(vector["platform_sso_secret"], body, vector["timestamp"], vector["jti"]) == vector["header"]
    # Тот же вектор принимается проверкой «в своё время».
    bootstrap.verify.__wrapped__ if hasattr(bootstrap.verify, "__wrapped__") else None
    bootstrap_settings = vector["platform_sso_secret"]
    from django.test import override_settings

    with override_settings(PLATFORM_SSO_SECRET=[bootstrap_settings]):
        bootstrap.verify(vector["header"], body, now=vector["timestamp"] + 10)


def test_no_proof_secret_or_jti_in_logs_or_responses(caplog):
    caplog.set_level(logging.DEBUG)
    body = raw()
    jti = uuid.uuid4().hex
    header = proof_for(body, jti=jti)
    responses = [
        post(body, header),
        post(body, header),  # повтор
        post(body, proof_for(body, secret="wrong")),
        post(body, proof_for(body, ts=1)),
    ]
    text = caplog.text + "".join(r.content.decode() for r in responses)
    for secret in (*SECRETS.values(), header, jti, SSO_SECRET, header.rsplit(".", 1)[1]):
        assert secret not in text
