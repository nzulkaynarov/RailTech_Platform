"""FIX-61: подпись вебхука v2 (Q-FIX35-2, CONTRACTS §3).

`X-Signature: sha256=HMAC(secret, "{X-Event-Id}.{X-Timestamp}.{body}")`; `X-Timestamp` — UTC ISO 8601, заново при каждой
попытке доставки (тот же `X-Event-Id`); подпись — по реальным байтам тела, которые уходят в запросе (с кодом акцепта).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Retry
from django.utils import timezone
from integration.models import WebhookEventStatus
from integration.services.webhooks import (
    emit_event,
    sign_payload,
    sign_payload_v2,
    signature_timestamp,
    verify_signature_v2,
)
from integration.tasks import deliver_webhook_event
from integration.tests.world import make_company

from core.tests.events_contract import example_event

pytestmark = pytest.mark.django_db

VECTOR_RELATIVE = Path("packages") / "contracts" / "examples" / "webhook-signature-v2.json"


def _vector() -> dict:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / VECTOR_RELATIVE
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    pytest.fail(f"нет общего тест-вектора {VECTOR_RELATIVE}: контейнер тестов обязан монтировать packages/contracts")


def _emit(settings, secret="fix61-secret"):
    settings.ERP_WEBHOOK_SECRET = secret
    company = make_company(crm_client_id=6101)
    body = example_event("quote.viewed")
    return emit_event(
        event_type="quote.viewed",
        erp_company_id=company.pk,
        payload=body["payload"],
        deal=body["deal"],
        actor=body["actor"],
        crm_client_id=6101,
        send_async=False,
    )


def _ok():
    return MagicMock(status_code=200, text="OK")


def test_common_vector_gives_the_same_signature_as_the_contract_file():
    """Те же secret/event_id/timestamp/body, что в тесте CRM: одна и та же подпись на обеих сторонах."""
    vec = _vector()
    assert sign_payload_v2(vec["secret"], vec["event_id"], vec["timestamp"], vec["body"].encode("utf-8")) == (
        vec["signature_v2"]
    )
    assert verify_signature_v2(
        vec["secret"], vec["event_id"], vec["timestamp"], vec["body"].encode("utf-8"), vec["signature_v2"]
    )
    # Сверка с эталонной формулой, написанной независимо от кода сервиса.
    signed = f"{vec['event_id']}.{vec['timestamp']}.{vec['body']}".encode()
    assert vec["signature_v2"] == "sha256=" + hmac.new(vec["secret"].encode(), signed, hashlib.sha256).hexdigest()
    # Старая схема (только тело) осталась как `sign_payload` — её вектор тоже общий.
    assert sign_payload(vec["secret"], vec["body"].encode("utf-8")) == vec["signature_legacy"]


def test_v2_signature_covers_event_id_and_timestamp_and_body():
    body = b'{"a":1}'
    base = sign_payload_v2("s", "id-1", "2026-10-21T09:30:00Z", body)
    assert base != sign_payload_v2("s", "id-2", "2026-10-21T09:30:00Z", body), "под новым X-Event-Id подпись другая"
    assert base != sign_payload_v2("s", "id-1", "2026-10-21T09:30:01Z", body), "под новой меткой подпись другая"
    assert base != sign_payload_v2("s", "id-1", "2026-10-21T09:30:00Z", b'{"a":2}')
    assert base != sign_payload("s", body), "v2 не совпадает со старой схемой"
    assert verify_signature_v2("s", "id-1", "2026-10-21T09:30:00Z", body, base)
    assert not verify_signature_v2("s", "id-2", "2026-10-21T09:30:00Z", body, base)


def test_signature_timestamp_is_utc_iso8601_with_z():
    ts = signature_timestamp()
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", ts)
    assert abs(datetime.fromisoformat(ts.replace("Z", "+00:00")) - timezone.now()) < timedelta(seconds=5)


def test_delivery_signs_v2_over_the_real_bytes_with_a_fresh_timestamp(settings):
    event = _emit(settings)
    with patch("httpx.Client.post", return_value=_ok()) as post:
        assert deliver_webhook_event(event.pk) is True
    sent = post.call_args.kwargs
    headers = sent["headers"]
    assert headers["X-Event-Id"] == str(event.event_id)
    assert headers["X-Timestamp"] != event.payload["occurred_at"], "метка подписи — момент отправки, не occurred_at"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", headers["X-Timestamp"])
    assert headers["X-Signature"] == sign_payload_v2(
        "fix61-secret", headers["X-Event-Id"], headers["X-Timestamp"], sent["content"]
    )
    assert headers["X-Signature"] != sign_payload("fix61-secret", sent["content"])
    event.refresh_from_db()
    assert event.headers["X-Timestamp"] == headers["X-Timestamp"], "журнал хранит заголовки последней попытки"


def test_every_retry_gets_a_new_timestamp_the_same_event_id_and_a_valid_signature(settings):
    event = _emit(settings)
    stamps = ["2026-10-21T10:00:00Z", "2026-10-21T10:05:00Z", "2026-10-21T10:35:00Z"]
    sent = []
    with patch("integration.tasks.signature_timestamp", side_effect=stamps):
        for _ in range(2):
            with patch("httpx.Client.post", return_value=MagicMock(status_code=503, text="down")) as post:
                with patch.object(deliver_webhook_event, "retry", side_effect=Retry("r")):
                    with pytest.raises(Retry):
                        deliver_webhook_event(event.pk)
            sent.append(post.call_args.kwargs)
        with patch("httpx.Client.post", return_value=_ok()) as post:
            assert deliver_webhook_event(event.pk) is True
        sent.append(post.call_args.kwargs)

    assert [s["headers"]["X-Timestamp"] for s in sent] == stamps
    assert {s["headers"]["X-Event-Id"] for s in sent} == {str(event.event_id)}
    for s in sent:
        h = s["headers"]
        assert verify_signature_v2("fix61-secret", h["X-Event-Id"], h["X-Timestamp"], s["content"], h["X-Signature"])
    assert len({s["headers"]["X-Signature"] for s in sent}) == 3, "подпись каждой попытки своя"


def test_manual_redelivery_after_the_grid_is_signed_afresh_too(settings):
    from integration.tasks import redeliver_event

    event = _emit(settings)
    with patch("integration.tasks.signature_timestamp", return_value="2026-10-21T11:00:00Z"):
        with patch("httpx.Client.post", return_value=_ok()):
            deliver_webhook_event(event.pk)
    event.refresh_from_db()
    assert event.status == WebhookEventStatus.SENT
    with patch("integration.tasks.deliver_webhook_event.delay"):
        redeliver_event(event.pk)
    with patch("integration.tasks.signature_timestamp", return_value="2026-10-22T11:00:00Z"):
        with patch("httpx.Client.post", return_value=_ok()) as post:
            deliver_webhook_event(event.pk)
    assert post.call_args.kwargs["headers"]["X-Timestamp"] == "2026-10-22T11:00:00Z"


def test_rotation_signs_with_the_first_secret_in_v2(settings):
    event = _emit(settings, secret="new-secret-value,old-secret-value")
    with patch("httpx.Client.post", return_value=_ok()) as post:
        deliver_webhook_event(event.pk)
    sent = post.call_args.kwargs
    h = sent["headers"]
    assert verify_signature_v2("new-secret-value", h["X-Event-Id"], h["X-Timestamp"], sent["content"], h["X-Signature"])
    assert not verify_signature_v2(
        "old-secret-value", h["X-Event-Id"], h["X-Timestamp"], sent["content"], h["X-Signature"]
    )
