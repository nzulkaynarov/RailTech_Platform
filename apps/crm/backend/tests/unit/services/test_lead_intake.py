"""Антиспам формы «Запрос» в сервисе (M3-CRM-05): до БД — honeypot, токен, окно по IP."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from app.domain.errors import RateLimitedError, ValidationFailedError
from app.domain.web_form import SlidingWindowLimiter, issue_form_token
from app.schemas.lead_intake import WebLeadIn
from app.schemas.settings import AppSettings
from app.services.lead_intake import LeadIntakeService

KEY = b"unit-form-key"
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


class _Settings:
    def __init__(self, cfg: AppSettings | None = None) -> None:
        self.cfg = cfg or AppSettings()

    async def get(self) -> AppSettings:
        return self.cfg


class _NoDb:
    """Сессии не должны понадобиться: антиспам срабатывает раньше."""

    def __call__(self) -> Any:
        raise AssertionError("database must not be touched")


def service(limiter: SlidingWindowLimiter | None = None, **cfg: Any) -> LeadIntakeService:
    settings = AppSettings(web_form=cfg) if cfg else AppSettings()
    return LeadIntakeService(cast(Any, _NoDb()), cast(Any, _Settings(settings)), KEY, limiter)


def body(**patch: Any) -> WebLeadIn:
    base: dict[str, Any] = {
        "name": "Алишер",
        "phone": "+998901234567",
        "text": "Нужна интеграция",
        "form_token": issue_form_token(KEY, NOW - timedelta(seconds=30)),
    }
    base.update(patch)
    return WebLeadIn(**base)


async def test_honeypot_is_silently_dropped() -> None:
    assert await service().create_web(body(website="http://spam"), "1.1.1.1", NOW) is None


@pytest.mark.parametrize(
    ("token", "reason"),
    [
        ("garbage", "form_token_invalid"),
        (issue_form_token(b"other", NOW - timedelta(seconds=30)), "form_token_invalid"),
        (issue_form_token(KEY, NOW), "form_too_fast"),
        (issue_form_token(KEY, NOW - timedelta(hours=2)), "form_token_expired"),
    ],
)
async def test_bad_tokens_are_422_with_reason(token: str, reason: str) -> None:
    with pytest.raises(ValidationFailedError) as info:
        await service().create_web(body(form_token=token), "1.1.1.1", NOW)
    assert info.value.details == {"reason": reason, "field": "form_token"}


async def test_rate_limit_per_ip_from_settings() -> None:
    limiter = SlidingWindowLimiter(limit=100, window_s=3600)
    svc = service(limiter, rate_limit_per_hour=2)
    # Два прохода антиспама «съедают» окно (БД не трогается: контакт не задан → 422 позже).
    for _ in range(2):
        with pytest.raises(ValidationFailedError) as info:
            await svc.create_web(body(phone=None, email=None), "9.9.9.9", NOW)
        assert info.value.details["reason"] == "contact_required"
    with pytest.raises(RateLimitedError):
        await svc.create_web(body(), "9.9.9.9", NOW + timedelta(seconds=1))
    # Другой адрес — своё окно.
    with pytest.raises(ValidationFailedError):
        await svc.create_web(body(phone=None), "8.8.8.8", NOW + timedelta(seconds=1))


async def test_form_token_response_uses_settings() -> None:
    token = await service(token_ttl_minutes=15, min_fill_seconds=5).form_token(NOW)
    assert token.expires_at == NOW + timedelta(minutes=15)
    assert token.min_fill_seconds == 5
    assert token.token == issue_form_token(KEY, NOW)


async def test_invalid_phone_is_a_field_error() -> None:
    with pytest.raises(ValidationFailedError) as info:
        await service().create_web(body(phone="abc"), "1.1.1.1", NOW)
    assert info.value.details == {"reason": "invalid_phone", "field": "phone"}
