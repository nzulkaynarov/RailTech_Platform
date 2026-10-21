"""Коннектор «ERP» (M3-CRM-02): «Проверить связь» через respx, сохранение с паролем, кэш здоровья.

Секреты не уходят в ответы, аудит и логи; без коннектора — «не настроен», а не ошибка.
"""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from app.config import Settings
from app.domain.backoffice import BackofficeMode
from app.domain.errors import ConflictError, Reason, UpstreamUnavailableError, ValidationFailedError
from app.domain.system_status import ErpFacts
from app.integrations.erp import HttpxErpProbe
from app.schemas.integrations import ErpConnectorIn, ErpStatusOut
from app.schemas.settings import IntegrationsSettings
from app.security.passwords import hash_password
from app.security.principal import Principal
from app.security.secrets_store import (
    ERP_SERVICE_TOKEN,
    ERP_WEBHOOK_SECRET,
    ERP_WEBHOOK_SECRET_PREVIOUS,
    SecretCipher,
    SecretsStore,
    SecretStatus,
)
from app.services import erp_connector as svc

TOKEN = "erp-service-token-for-unit-tests-Q1w2"  # фиктивный, в сеть не уходит
HOOK = "erp-webhook-secret-for-unit-tests-Z9x8"  # фиктивный
PASSWORD = "admin-pass-123"  # фиктивный пароль теста
ADMIN = Principal(user_id=1, full_name="Админ", roles=("admin",))
BASE = "https://erp.example"
HEALTH = f"{BASE}/api/integration/v1/health"
HEALTHY = {
    "status": "ok",
    "version": "1.2.3",
    "migrations_applied": True,
    "queue_alive": True,
    "checked_at": "2026-10-13T09:00:00+05:00",
}


class FakeSession:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


def fake_sessions() -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    return factory


class FakeStore(SecretsStore):
    def __init__(self, *, enabled: bool = True, **stored: str) -> None:
        cipher = SecretCipher(secrets.token_hex(32)) if enabled else None
        super().__init__(fake_sessions(), cipher)
        self.saved: dict[str, str] = dict(stored)
        self.put_sessions: list[int] = []

    async def get(self, key: str) -> str | None:
        return self.saved.get(key) if self.enabled else None

    async def put(self, session: Any, key: str, value: str, user_id: int | None) -> None:
        self.put_sessions.append(id(session))
        self.saved[key] = value

    async def delete(self, session: Any, key: str) -> None:
        self.saved.pop(key, None)

    async def status(self, key: str) -> SecretStatus | None:
        value = self.saved.get(key)
        return None if value is None else SecretStatus(value[-4:], None)  # type: ignore[arg-type]


class FakeSettings:
    def __init__(self, base_url: str = "") -> None:
        self.value = IntegrationsSettings(erp_base_url=base_url)
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.session_ids: list[int] = []
        self.invalidations = 0

    @property
    def base_url(self) -> str:
        return self.value.erp_base_url

    async def get(self) -> Any:
        return SimpleNamespace(integrations=self.value)

    async def update(self, key: str, value: dict[str, Any], user_id: int | None) -> Any:
        self.updates.append((key, value))
        self.value = IntegrationsSettings.model_validate(value)
        return value

    async def update_in(
        self, session: Any, key: str, value: dict[str, Any], user_id: int | None
    ) -> Any:
        """Запись в транзакции вызывающего; сессия запоминается для сверки с сессией секретов."""
        self.session_ids.append(id(session))
        return await self.update(key, value, user_id)

    def invalidate(self) -> None:
        self.invalidations += 1


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def audit_log(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    async def record(*args: Any, **kwargs: Any) -> None:
        records.append({"args": args, **kwargs})

    user = SimpleNamespace(
        id=0, password_hash=hash_password(PASSWORD), failed_logins=0, locked_until=None
    )

    async def get_user(session: Any, user_id: int, **_: Any) -> Any:
        user.id = user_id
        return user

    monkeypatch.setattr("app.services.erp_connector.audit.record", record)
    monkeypatch.setattr("app.services.erp_connector.users_repo.get", get_user)
    return records


def make(
    store: FakeStore | None = None,
    settings: FakeSettings | None = None,
    *,
    config: Settings | None = None,
    clock: Clock | None = None,
) -> tuple[svc.ErpConnectorService, FakeStore, FakeSettings]:
    store = store or FakeStore()
    settings = settings or FakeSettings()
    service = svc.ErpConnectorService(
        fake_sessions(),
        settings,  # type: ignore[arg-type]
        store,
        config or Settings(_env_file=None),
        HttpxErpProbe(timeout_s=0.2),
        clock=clock or Clock(),
    )
    return service, store, settings


def configured(**kwargs: Any) -> tuple[svc.ErpConnectorService, FakeStore, FakeSettings]:
    return make(FakeStore(erp_service_token=TOKEN), FakeSettings(BASE), **kwargs)


# --- «Проверить связь» -------------------------------------------------------------


@respx.mock
async def test_check_success_returns_health_and_sends_bearer() -> None:
    route = respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, _ = configured()
    health = await service.check()
    assert (health.status, health.version) == ("ok", "1.2.3")
    assert health.migrations_applied
    assert health.queue_alive
    assert health.latency_ms >= 0
    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    facts = await service.health_facts()
    assert facts == ErpFacts(
        configured=True,
        status="ok",
        version="1.2.3",
        migrations_applied=True,
        queue_alive=True,
        checked_at=health.checked_at,
        latency_ms=health.latency_ms,
    )


@respx.mock
@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(401, json={"detail": "UNAUTHORIZED"}), Reason.ERP_UNAUTHORIZED),
        (httpx.Response(403), Reason.ERP_UNAUTHORIZED),
        (httpx.Response(500), Reason.ERP_BAD_RESPONSE),
        (httpx.Response(200, text="<html>"), Reason.ERP_BAD_RESPONSE),
        (httpx.Response(200, json={"status": "ok"}), Reason.ERP_BAD_RESPONSE),
        (httpx.Response(200, json={**HEALTHY, "status": "down"}), Reason.ERP_BAD_RESPONSE),
        (httpx.TimeoutException("slow"), Reason.ERP_UNAVAILABLE),
        (httpx.ConnectError("refused"), Reason.ERP_UNAVAILABLE),
    ],
    ids=["401", "403", "500", "html", "partial", "bad-enum", "timeout", "connect"],
)
async def test_check_failures_map_to_reasons(response: Any, reason: Reason) -> None:
    if isinstance(response, Exception):
        respx.get(HEALTH).mock(side_effect=response)
    else:
        respx.get(HEALTH).mock(return_value=response)
    service, _, _ = configured()
    with pytest.raises(UpstreamUnavailableError) as caught:
        await service.check()
    assert caught.value.details["reason"] == reason
    facts = await service.health_facts()
    assert facts.configured
    assert facts.error is not None
    assert TOKEN not in repr(caught.value.details)


async def test_check_without_connector_is_not_configured() -> None:
    service, _, _ = make()
    with pytest.raises(ConflictError) as caught:
        await service.check()
    assert caught.value.details["reason"] == Reason.ERP_NOT_CONFIGURED
    assert await service.health_facts() == ErpFacts(configured=False)
    assert await service.mode() == BackofficeMode.LOCAL


@respx.mock
async def test_check_invalid_url_is_validation_error() -> None:
    config = Settings(_env_file=None, erp_base_url="erp.example", erp_service_token=TOKEN)
    service, _, _ = make(config=config)
    with pytest.raises(ValidationFailedError) as caught:
        await service.check()
    assert caught.value.details == {"reason": Reason.ERP_INVALID_URL, "field": "base_url"}
    assert not respx.calls


# --- Кэш здоровья для «Состояния системы» ---------------------------------------------


@respx.mock
async def test_health_facts_cached_for_30s_and_refreshed_by_check() -> None:
    route = respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    clock = Clock()
    service, _, _ = configured(clock=clock)
    await service.health_facts()
    await service.health_facts()
    assert route.call_count == 1
    clock.now += 29
    await service.health_facts()
    assert route.call_count == 1
    clock.now += 2
    await service.health_facts()
    assert route.call_count == 2
    await service.check()  # кнопка всегда идёт в ERP
    assert route.call_count == 3


@respx.mock
async def test_health_facts_do_not_raise_on_failure() -> None:
    respx.get(HEALTH).mock(side_effect=httpx.ConnectError("refused"))
    service, _, _ = configured()
    facts = await service.health_facts()
    assert (facts.configured, facts.error) == (True, "unavailable")


# --- Сохранение ---------------------------------------------------------------------


async def test_wrong_password_saves_nothing(audit_log: list[dict[str, Any]]) -> None:
    service, store, settings = make()
    with pytest.raises(ValidationFailedError) as caught:
        await service.save(
            ADMIN, base_url=BASE, service_token=TOKEN, webhook_secret=None, password="nope"
        )
    assert caught.value.details["reason"] == Reason.WRONG_PASSWORD
    assert store.saved == {}
    assert settings.updates == []
    assert audit_log == []


async def test_invalid_url_rejected_before_password(audit_log: list[dict[str, Any]]) -> None:
    service, _, settings = make()
    with pytest.raises(ValidationFailedError) as caught:
        await service.save(
            ADMIN, base_url="erp.example", service_token=None, webhook_secret=None, password="x"
        )
    assert caught.value.details == {"reason": Reason.ERP_INVALID_URL, "field": "base_url"}
    assert settings.updates == []
    assert audit_log == []


async def test_secrets_need_secrets_key(audit_log: list[dict[str, Any]]) -> None:
    service, _, settings = make(FakeStore(enabled=False))
    with pytest.raises(ConflictError) as caught:
        await service.save(
            ADMIN, base_url=BASE, service_token=TOKEN, webhook_secret=None, password=PASSWORD
        )
    assert caught.value.details["reason"] == Reason.SECRETS_KEY_MISSING
    assert settings.updates == []
    # Без SECRETS_KEY адрес сохранить можно: токен тогда — из `.env`.
    status = await service.save(
        ADMIN, base_url=BASE, service_token=None, webhook_secret=None, password=PASSWORD
    )
    assert (status.base_url, status.secrets_enabled, status.configured) == (BASE, False, False)


@respx.mock
async def test_save_audits_without_values_and_switches_mode(
    audit_log: list[dict[str, Any]],
) -> None:
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, store, settings = make()
    assert await service.mode() == BackofficeMode.LOCAL
    with capture_logs() as logs:
        status = await service.save(
            ADMIN,
            base_url=f"{BASE}/api/integration/v1/",
            service_token=f" {TOKEN} ",
            webhook_secret=HOOK,
            password=PASSWORD,
        )
    assert store.saved == {ERP_SERVICE_TOKEN: TOKEN, ERP_WEBHOOK_SECRET: HOOK}
    assert [(key, value["erp_base_url"]) for key, value in settings.updates] == [
        ("integrations", BASE)
    ]
    assert settings.value.smtp == IntegrationsSettings().smtp, (
        "сохранение ERP не затирает остальные ключи «Подключений»"
    )
    assert status.configured
    assert status.mode == BackofficeMode.ERP
    assert (status.base_url_source, status.token_source) == ("db", "db")
    assert (status.token_last4, status.webhook_secret_last4) == ("Q1w2", "Z9x8")
    assert await service.mode() == BackofficeMode.ERP
    [entry] = audit_log
    assert entry["args"][2:5] == ("integrations.erp", "integration", "erp")
    assert entry["after"] == {
        "base_url": BASE,
        "erp_service_token_last4": "Q1w2",
        "erp_webhook_secret_last4": "Z9x8",
        "erp_webhook_secret_previous_last4": None,
    }
    for secret in (TOKEN, HOOK, PASSWORD):
        assert secret not in repr(audit_log)
        assert secret not in repr(logs)
        assert secret not in ErpStatusOut(**{**asdict(status), "mode": "erp"}).model_dump_json()


async def test_save_keeps_secrets_when_none(audit_log: list[dict[str, Any]]) -> None:
    service, store, _ = configured()
    status = await service.save(
        ADMIN,
        base_url="https://erp.new",
        service_token=None,
        webhook_secret=None,
        password=PASSWORD,
    )
    assert store.saved == {ERP_SERVICE_TOKEN: TOKEN}
    assert (status.base_url, status.token_last4) == ("https://erp.new", "Q1w2")
    assert audit_log[0]["before"]["base_url"] == BASE


async def test_empty_url_disables_connector(audit_log: list[dict[str, Any]]) -> None:
    service, _, _ = configured()
    status = await service.save(
        ADMIN, base_url="  ", service_token=None, webhook_secret=None, password=PASSWORD
    )
    assert (status.configured, status.mode, status.base_url_source) == (
        False,
        BackofficeMode.LOCAL,
        "none",
    )


def test_input_is_masked_in_repr() -> None:
    body = ErpConnectorIn.model_validate(
        {"base_url": BASE, "service_token": TOKEN, "webhook_secret": HOOK, "password": PASSWORD}
    )
    for secret in (TOKEN, HOOK, PASSWORD):
        assert secret not in repr(body)
        assert secret not in body.model_dump_json()


# --- Ротация секрета вебхуков без простоя (FIX-35) ------------------------------------------------

OLD_HOOK = "erp-webhook-secret-OLD-for-unit-tests-0001"  # фиктивный
NEW_HOOK = "erp-webhook-secret-NEW-for-unit-tests-0002"  # фиктивный


async def test_rotation_new_current_old_previous_then_previous_is_cleared(
    audit_log: list[dict[str, Any]],
) -> None:
    service, store, _ = make(FakeStore(erp_webhook_secret=OLD_HOOK))
    assert (await service.resolution()).webhook_secrets == (OLD_HOOK,)

    status = await service.save(
        ADMIN,
        base_url=BASE,
        service_token=None,
        webhook_secret=NEW_HOOK,
        webhook_secret_previous=OLD_HOOK,
        password=PASSWORD,
    )
    assert (await service.resolution()).webhook_secrets == (NEW_HOOK, OLD_HOOK)
    assert status.webhook_secret_previous_configured
    assert status.webhook_secret_previous_source == "db"
    assert status.webhook_secret_previous_last4 == OLD_HOOK[-4:]

    status = await service.save(
        ADMIN,
        base_url=BASE,
        service_token=None,
        webhook_secret=None,
        clear_webhook_secret_previous=True,
        password=PASSWORD,
    )
    assert ERP_WEBHOOK_SECRET_PREVIOUS not in store.saved
    assert (await service.resolution()).webhook_secrets == (NEW_HOOK,)
    assert not status.webhook_secret_previous_configured
    assert status.webhook_secret_previous_source == "none"
    audits = [entry["after"] for entry in audit_log]
    assert audits[0]["erp_webhook_secret_previous_last4"] == OLD_HOOK[-4:]
    assert audits[1]["erp_webhook_secret_previous_last4"] is None
    for secret in (OLD_HOOK, NEW_HOOK):
        assert secret not in repr(audit_log)
        assert secret not in ErpStatusOut(**{**asdict(status), "mode": "local"}).model_dump_json()


async def test_a_new_previous_secret_wins_over_clear_in_one_request(
    audit_log: list[dict[str, Any]],
) -> None:
    service, store, _ = make()
    await service.save(
        ADMIN,
        base_url=BASE,
        service_token=None,
        webhook_secret=NEW_HOOK,
        webhook_secret_previous=OLD_HOOK,
        clear_webhook_secret_previous=True,
        password=PASSWORD,
    )
    assert store.saved[ERP_WEBHOOK_SECRET_PREVIOUS] == OLD_HOOK


async def test_clearing_the_previous_secret_needs_secrets_key(
    audit_log: list[dict[str, Any]],
) -> None:
    service, _, _ = make(FakeStore(enabled=False))
    with pytest.raises(ConflictError) as caught:
        await service.save(
            ADMIN,
            base_url=BASE,
            service_token=None,
            webhook_secret=None,
            clear_webhook_secret_previous=True,
            password=PASSWORD,
        )
    assert caught.value.details["reason"] == Reason.SECRETS_KEY_MISSING


def test_connector_form_schema_accepts_the_previous_secret_and_the_clear_flag() -> None:
    body = ErpConnectorIn.model_validate(
        {
            "base_url": BASE,
            "webhook_secret": NEW_HOOK,
            "webhook_secret_previous": OLD_HOOK,
            "clear_webhook_secret_previous": False,
            "password": PASSWORD,
        }
    )
    assert body.webhook_secret_previous is not None
    assert body.webhook_secret_previous.get_secret_value() == OLD_HOOK
    with pytest.raises(ValueError, match="at least 16"):
        ErpConnectorIn.model_validate(
            {"base_url": BASE, "webhook_secret_previous": "short", "password": PASSWORD}
        )


@pytest.mark.parametrize("field", ["service_token", "webhook_secret", "webhook_secret_previous"])
@pytest.mark.parametrize("blank", [" " * 20, "\t\n" * 10, "  short  " + " " * 12])
def test_a_secret_of_whitespace_is_refused_before_it_is_stripped(field: str, blank: str) -> None:
    with pytest.raises(ValueError, match="besides whitespace"):
        ErpConnectorIn.model_validate({"base_url": BASE, field: blank, "password": PASSWORD})
