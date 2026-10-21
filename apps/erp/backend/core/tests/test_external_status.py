"""M3-ERP-06: примитивы состояния внешних сервисов ERP — счётчики за 24 ч, метки, выключатели, короткий текст ошибки."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from core import external_status as ext

pytestmark = pytest.mark.django_db


def test_counters_count_only_the_last_24_hours():
    now = timezone.now()
    ext.record_success("s3", at=now - datetime.timedelta(hours=30))
    ext.record_success("s3", at=now - datetime.timedelta(hours=5))
    ext.record_success("s3", at=now - datetime.timedelta(minutes=1))
    ext.record_failure("s3", RuntimeError("boom"), at=now - datetime.timedelta(hours=2))

    assert ext.counts("s3", now=now) == (2, 1)
    assert ext.counts("mail", now=now) == (0, 0), "счётчики разных сервисов не смешиваются"


def test_last_marks_remember_the_newest_success_and_error():
    now = timezone.now()
    assert ext.last_marks("s3") == (None, None, None)
    ext.record_failure("s3", RuntimeError("first"), at=now - datetime.timedelta(hours=3))
    ext.record_success("s3", at=now - datetime.timedelta(hours=2))
    ext.record_failure("s3", ConnectionError("second"), at=now - datetime.timedelta(hours=1))

    success_at, error_at, error = ext.last_marks("s3")
    assert success_at == now - datetime.timedelta(hours=2)
    assert error_at == now - datetime.timedelta(hours=1)
    assert error == "ConnectionError: second"


def test_recording_never_breaks_the_caller_when_the_cache_is_down(monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr("django.core.cache.cache.incr", broken)
    monkeypatch.setattr("django.core.cache.cache.add", broken)
    monkeypatch.setattr("django.core.cache.cache.set", broken)
    ext.record_success("s3")
    ext.record_failure("s3", RuntimeError("x"))


def test_unknown_code_is_a_programming_error():
    with pytest.raises(KeyError):
        ext.record_success("telegram")


def test_services_are_enabled_by_default_and_the_switch_survives_a_cache_flush():
    from django.core.cache import cache

    assert ext.is_enabled("mail") is True
    state = ext.set_enabled("mail", False, reason="  утечка ключа  ")
    assert state.enabled is False and state.reason == "утечка ключа"
    assert ext.is_enabled("mail") is False
    cache.clear()  # Redis потерян — выключатель остался в базе
    assert ext.is_enabled("mail") is False
    assert ext.is_enabled("s3") is True, "другие сервисы не затронуты"

    ext.set_enabled("mail", True)
    assert ext.is_enabled("mail") is True
    cache.clear()
    assert ext.is_enabled("mail") is True


def test_switch_is_idempotent_and_keeps_one_row():
    from core.models import ExternalServiceSwitch

    ext.set_enabled("litellm", False)
    ext.set_enabled("litellm", False)
    assert ExternalServiceSwitch.objects.filter(code="litellm").count() == 1


def test_sentry_cannot_be_switched():
    with pytest.raises(ext.NotSwitchable):
        ext.set_enabled("sentry", False)


def test_external_call_records_success_and_failure_and_respects_the_switch():
    with ext.external_call("cbu_rates"):
        pass
    with pytest.raises(ValueError):
        with ext.external_call("cbu_rates"):
            raise ValueError("bad payload")
    assert ext.counts("cbu_rates") == (1, 1)

    ext.set_enabled("cbu_rates", False)
    ran = []
    with pytest.raises(ext.ExternalSwitchedOff):
        with ext.external_call("cbu_rates"):
            ran.append(True)
    assert not ran, "тело не выполняется, пока сервис выключен"
    assert ext.counts("cbu_rates") == (1, 1), "отказ выключателя — не сбой сервиса"


@pytest.mark.parametrize(
    ("raw", "forbidden"),
    [
        ("ConnectError: https://admin:hunter2@smtp.example.com:587/path?token=abc", ["hunter2", "abc", "/path"]),
        ("HTTPStatusError: Authorization: Bearer sk-live-0123456789abcdef0123456789", ["sk-live", "0123456789abcdef"]),
        ("OperationalError: password=hunter2 host=db", ["hunter2"]),
        ("SMTPAuthenticationError: (535, b'user@example.com rejected')", ["user@example.com"]),
        ("ClientError: key AKIAIOSFODNN7EXAMPLE denied", ["AKIAIOSFODNN7EXAMPLE"]),
    ],
)
def test_short_error_hides_secrets(raw, forbidden):
    text = ext.short_error(raw)
    for secret in forbidden:
        assert secret not in text
    assert len(text) <= 200


def test_short_error_keeps_the_class_and_is_truncated():
    assert ext.short_error(ConnectionError("Connection refused")) == "ConnectionError: Connection refused"
    long = ext.short_error(RuntimeError("x " * 500))
    assert len(long) <= 200 and long.startswith("RuntimeError: ")
    assert ext.short_error("") == "Error"
