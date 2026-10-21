"""Сопряжение CRM ↔ ERP в один клик (M3-CRM-10): «Подключить ERP» и «Обновить ключи».

ERP подменена respx. Проверяется: CRM сама генерирует три секрета и отправляет их под кодом;
сохраняет только после успеха ERP; сразу делает «Проверить связь»; ошибки кода (неверный,
просрочен, использован) — понятные подкоды без изменений в хранилище; пароль админа обязателен;
ротация принимает оба секрета вебхуков заранее и откатывает их при отказе ERP; предыдущий секрет
снимается по истечении перехода; ни кодов, ни токенов в логах, аудите и `repr`.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from app.config import Settings
from app.domain.errors import ConflictError, Reason, UpstreamUnavailableError, ValidationFailedError
from app.integrations.erp import HttpxErpProbe
from app.integrations.erp_pairing import HttpxErpPairingClient, PairingSecrets
from app.security.secrets_store import (
    ERP_INBOUND_TOKEN,
    ERP_SERVICE_TOKEN,
    ERP_WEBHOOK_SECRET,
    ERP_WEBHOOK_SECRET_PREVIOUS,
)
from app.services import erp_connector as connector_svc
from app.services.erp_pairing import ErpPairingService
from tests.unit.services.test_erp_connector import (
    ADMIN,
    BASE,
    HEALTH,
    HEALTHY,
    PASSWORD,
    FakeSettings,
    FakeStore,
    audit_log,  # noqa: F401  (фикстура: аудит и пользователь без БД)
    fake_sessions,
)

ACCEPT = f"{BASE}/api/integration/v1/pairing/accept"
ROTATE = f"{BASE}/api/integration/v1/pairing/rotate"
pytestmark = pytest.mark.usefixtures("audit_log")  # аудит и проверка пароля без БД

CODE = "ABCD-EFGH-JKMN"  # фиктивный код сопряжения
OLD_TOKEN = "old-crm-to-erp-token-for-unit-tests-Q1w2"  # фиктивный
OLD_HOOK = "old-webhook-secret-for-unit-tests-Z9x8"  # фиктивный
ACCEPTED = {
    "paired": True,
    "paired_at": "2026-10-21T10:00:00+05:00",
    "erp_version": "1.2.3",
    "new_field": 1,
}
ROTATED = {
    "rotated": True,
    "rotated_at": "2026-10-21T10:00:00+05:00",
    "previous_token_valid_until": "2026-10-21T11:00:00+05:00",
}


def make(
    store: FakeStore | None = None, settings: FakeSettings | None = None, *, grace_s: int = 3600
) -> tuple[ErpPairingService, connector_svc.ErpConnectorService, FakeStore, FakeSettings]:
    store = store or FakeStore()
    settings = settings or FakeSettings()
    config = Settings(_env_file=None)
    connector = connector_svc.ErpConnectorService(
        fake_sessions(),
        settings,  # type: ignore[arg-type]
        store,
        config,
        HttpxErpProbe(timeout_s=0.2),
    )
    service = ErpPairingService(
        fake_sessions(),
        settings,  # type: ignore[arg-type]
        store,
        config,
        HttpxErpPairingClient(timeout_s=0.2),
        connector,
        rotation_grace_s=grace_s,
    )
    return service, connector, store, settings


def stored(**values: str) -> FakeStore:
    """Хранилище с готовыми секретами (ключи — константы `secrets_store`, не имена параметров)."""
    store = FakeStore()
    store.saved.update(values)
    return store


def sent_body(route: respx.Route) -> dict[str, str]:
    body: dict[str, str] = json.loads(route.calls.last.request.content)
    return body


# --- Подключить ERP -------------------------------------------------------------------


@respx.mock
async def test_pair_generates_secrets_sends_them_under_the_code_and_checks_the_link(
    audit_log: list[dict[str, Any]],  # noqa: F811
) -> None:
    accept = respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    health = respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, store, settings = make()

    with capture_logs() as logs:
        outcome = await service.pair(
            ADMIN, base_url=f"{BASE}/", code=f"  {CODE} ", password=PASSWORD
        )

    request = accept.calls.last.request
    assert request.headers["authorization"] == f"Bearer {CODE}", (
        "ERP получает код, а не сервисный токен"
    )
    body = sent_body(accept)
    assert set(body) == {"crm_to_erp_token", "erp_to_crm_token", "webhook_secret"}
    assert len({*body.values()}) == 3
    assert all(len(v) >= 32 for v in body.values())
    # Сохранено ровно то, что ушло в ERP.
    assert store.saved == {
        ERP_SERVICE_TOKEN: body["crm_to_erp_token"],
        ERP_INBOUND_TOKEN: body["erp_to_crm_token"],
        ERP_WEBHOOK_SECRET: body["webhook_secret"],
    }
    assert settings.base_url == BASE
    # «Проверить связь» уже с новым токеном.
    assert (
        health.calls.last.request.headers["authorization"] == f"Bearer {body['crm_to_erp_token']}"
    )
    assert outcome.check is not None
    assert outcome.check.status == "ok"
    assert outcome.check_error is None
    assert outcome.status.paired
    assert outcome.status.configured
    assert outcome.status.inbound_token_last4 == body["erp_to_crm_token"][-4:]
    assert (outcome.status.token_source, outcome.status.webhook_secret_source) == ("db", "db")
    # Ни кода, ни секретов в логах и аудите.
    dump = json.dumps([logs, audit_log], default=str)
    for secret in (CODE, *body.values()):
        assert secret not in dump


@respx.mock
async def test_pair_clears_previous_webhook_secret_and_keeps_other_settings() -> None:
    respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    store = stored(**{ERP_WEBHOOK_SECRET_PREVIOUS: OLD_HOOK})
    service, _, store, settings = make(store)
    await service.pair(ADMIN, base_url=BASE, code=CODE, password=PASSWORD)
    assert ERP_WEBHOOK_SECRET_PREVIOUS not in store.saved
    assert settings.value.erp_previous_secret_until is None


@respx.mock
async def test_pair_succeeds_even_if_the_link_check_fails() -> None:
    respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    respx.get(HEALTH).mock(return_value=httpx.Response(401, json={"detail": "UNAUTHORIZED"}))
    service, _, store, _ = make()
    outcome = await service.pair(ADMIN, base_url=BASE, code=CODE, password=PASSWORD)
    assert outcome.check is None
    assert outcome.check_error == "erp_unauthorized"
    assert outcome.status.paired, "ключи сохранены — сопряжение состоялось, проверка объяснена"
    assert ERP_SERVICE_TOKEN in store.saved


@pytest.mark.parametrize(
    ("detail", "reason"),
    [
        ("PAIRING_CODE_INVALID", Reason.ERP_PAIRING_CODE_INVALID),
        ("PAIRING_CODE_EXPIRED", Reason.ERP_PAIRING_CODE_EXPIRED),
        ("PAIRING_CODE_USED", Reason.ERP_PAIRING_CODE_USED),
        ("SOMETHING_NEW", Reason.ERP_PAIRING_CODE_INVALID),
    ],
)
@respx.mock
async def test_pair_rejected_code_changes_nothing(detail: str, reason: Reason) -> None:
    respx.post(ACCEPT).mock(return_value=httpx.Response(401, json={"detail": detail}))
    store = stored(**{ERP_SERVICE_TOKEN: OLD_TOKEN})
    service, _, store, settings = make(store)
    with pytest.raises(ValidationFailedError) as caught:
        await service.pair(ADMIN, base_url=BASE, code=CODE, password=PASSWORD)
    assert caught.value.details == {"reason": reason.value, "field": "code"}
    assert store.saved == {ERP_SERVICE_TOKEN: OLD_TOKEN}, "прежние ключи не тронуты"
    assert settings.updates == []


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.Response(404), Reason.ERP_PAIRING_UNSUPPORTED),
        (httpx.Response(429, headers={"Retry-After": "30"}), Reason.ERP_UNAVAILABLE),
        (httpx.Response(422, json={"detail": "VALIDATION_ERROR"}), Reason.ERP_BAD_RESPONSE),
        (httpx.Response(500), Reason.ERP_BAD_RESPONSE),
        (httpx.Response(200, json={"paired": True}), Reason.ERP_BAD_RESPONSE),
        (httpx.ConnectError("boom"), Reason.ERP_UNAVAILABLE),
    ],
)
@respx.mock
async def test_pair_erp_failures_are_explained_and_change_nothing(
    response: httpx.Response | Exception, reason: Reason
) -> None:
    route = respx.post(ACCEPT)
    route.mock(side_effect=response) if isinstance(response, Exception) else route.mock(
        return_value=response
    )
    service, _, store, settings = make()
    with pytest.raises(UpstreamUnavailableError) as caught:
        await service.pair(ADMIN, base_url=BASE, code=CODE, password=PASSWORD)
    assert caught.value.details["reason"] == reason.value
    assert store.saved == {}
    assert settings.updates == []


@respx.mock
async def test_pair_requires_the_admin_password_before_calling_erp() -> None:
    route = respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    service, _, store, _ = make()
    with pytest.raises(ValidationFailedError) as caught:
        await service.pair(ADMIN, base_url=BASE, code=CODE, password="wrong")
    assert caught.value.details["reason"] == Reason.WRONG_PASSWORD.value
    assert not route.called
    assert store.saved == {}


@respx.mock
async def test_pair_without_secrets_key_is_conflict_and_does_not_burn_the_code() -> None:
    route = respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    service, _, _, _ = make(FakeStore(enabled=False))
    with pytest.raises(ConflictError) as caught:
        await service.pair(ADMIN, base_url=BASE, code=CODE, password=PASSWORD)
    assert caught.value.details["reason"] == Reason.SECRETS_KEY_MISSING.value
    assert not route.called, "код не тратим, пока секрет некуда сохранить"


@pytest.mark.parametrize(
    ("base_url", "code", "field"),
    [("erp.example", CODE, "base_url"), (BASE, "   ", "code"), ("ftp://erp", CODE, "base_url")],
)
async def test_pair_validates_input(base_url: str, code: str, field: str) -> None:
    service, _, _, _ = make()
    with pytest.raises(ValidationFailedError) as caught:
        await service.pair(ADMIN, base_url=base_url, code=code, password=PASSWORD)
    assert caught.value.details["field"] == field


@respx.mock
async def test_pair_normalizes_base_url_with_integration_prefix() -> None:
    route = respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, _, settings = make()
    await service.pair(ADMIN, base_url=f"{BASE}/api/integration/v1/", code=CODE, password=PASSWORD)
    assert route.called
    assert settings.base_url == BASE


# --- Обновить ключи -------------------------------------------------------------------


def paired_store() -> FakeStore:
    return stored(
        **{
            ERP_SERVICE_TOKEN: OLD_TOKEN,
            ERP_INBOUND_TOKEN: "old-erp-to-crm-token-for-unit-tests-Aa11",
            ERP_WEBHOOK_SECRET: OLD_HOOK,
        }
    )


@respx.mock
async def test_rotate_sends_new_triplet_under_the_current_token_and_swaps_secrets(
    audit_log: list[dict[str, Any]],  # noqa: F811
) -> None:
    rotate = respx.post(ROTATE).mock(return_value=httpx.Response(200, json=ROTATED))
    health = respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, store, settings = make(paired_store(), FakeSettings(BASE))

    with capture_logs() as logs:
        outcome = await service.rotate(ADMIN, password=PASSWORD)

    assert rotate.calls.last.request.headers["authorization"] == f"Bearer {OLD_TOKEN}"
    body = sent_body(rotate)
    assert body["crm_to_erp_token"] != OLD_TOKEN
    assert body["webhook_secret"] != OLD_HOOK
    assert store.saved[ERP_SERVICE_TOKEN] == body["crm_to_erp_token"]
    assert store.saved[ERP_INBOUND_TOKEN] == body["erp_to_crm_token"]
    assert store.saved[ERP_WEBHOOK_SECRET] == body["webhook_secret"]
    assert store.saved[ERP_WEBHOOK_SECRET_PREVIOUS] == OLD_HOOK, (
        "прежний секрет принимается в переход"
    )
    assert settings.value.erp_previous_secret_until is not None
    assert (
        health.calls.last.request.headers["authorization"] == f"Bearer {body['crm_to_erp_token']}"
    )
    assert outcome.check is not None
    assert outcome.status.previous_secret_until is not None
    dump = json.dumps([logs, audit_log], default=str)
    for secret in (OLD_TOKEN, OLD_HOOK, *body.values()):
        assert secret not in dump


@respx.mock
async def test_rotate_accepts_both_webhook_secrets_before_erp_switches() -> None:
    seen: dict[str, str | None] = {}

    def erp(request: httpx.Request) -> httpx.Response:
        # В момент вызова ERP CRM уже хранит новый секрет текущим и старый предыдущим.
        seen["current"] = store.saved.get(ERP_WEBHOOK_SECRET)
        seen["previous"] = store.saved.get(ERP_WEBHOOK_SECRET_PREVIOUS)
        seen["sent"] = json.loads(request.content)["webhook_secret"]
        return httpx.Response(200, json=ROTATED)

    respx.post(ROTATE).mock(side_effect=erp)
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, store, _ = make(paired_store(), FakeSettings(BASE))
    await service.rotate(ADMIN, password=PASSWORD)
    assert seen["current"] == seen["sent"]
    assert seen["previous"] == OLD_HOOK


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"detail": "UNAUTHORIZED"}),
        httpx.Response(500),
        httpx.ConnectError("x"),
    ],
)
@respx.mock
async def test_rotate_failure_rolls_back_and_keeps_old_keys(
    response: httpx.Response | Exception,
) -> None:
    route = respx.post(ROTATE)
    route.mock(side_effect=response) if isinstance(response, Exception) else route.mock(
        return_value=response
    )
    store = paired_store()
    store.saved[ERP_WEBHOOK_SECRET_PREVIOUS] = "manual-previous-secret-for-unit-tests-0001"
    before = dict(store.saved)
    service, _, store, settings = make(store, FakeSettings(BASE))
    with pytest.raises(UpstreamUnavailableError):
        await service.rotate(ADMIN, password=PASSWORD)
    assert store.saved == before, "ключи и предыдущий секрет возвращены как были"
    assert settings.value.erp_previous_secret_until is None


@respx.mock
async def test_rotate_failure_with_env_webhook_secret_removes_db_rows() -> None:
    respx.post(ROTATE).mock(return_value=httpx.Response(500))
    config = Settings(_env_file=None, erp_webhook_secret="env-webhook-secret-unit-test-0001")
    store = stored(**{ERP_SERVICE_TOKEN: OLD_TOKEN})
    settings = FakeSettings(BASE)
    sessions = fake_sessions()
    connector = connector_svc.ErpConnectorService(
        sessions,
        settings,  # type: ignore[arg-type]
        store,
        config,
        HttpxErpProbe(timeout_s=0.2),
    )
    service = ErpPairingService(
        sessions,
        settings,  # type: ignore[arg-type]
        store,
        config,
        HttpxErpPairingClient(0.2),
        connector,
    )
    with pytest.raises(UpstreamUnavailableError):
        await service.rotate(ADMIN, password=PASSWORD)
    assert store.saved == {ERP_SERVICE_TOKEN: OLD_TOKEN}


async def test_rotate_requires_a_configured_connector_and_the_password() -> None:
    service, _, _, _ = make()
    with pytest.raises(ConflictError) as caught:
        await service.rotate(ADMIN, password=PASSWORD)
    assert caught.value.details["reason"] == Reason.ERP_NOT_CONFIGURED.value
    service, _, _, _ = make(paired_store(), FakeSettings(BASE))
    with pytest.raises(ValidationFailedError):
        await service.rotate(ADMIN, password="wrong")


# --- Срок перехода --------------------------------------------------------------------


@respx.mock
async def test_previous_secret_is_dropped_after_the_transition_but_manual_one_stays() -> None:
    respx.post(ROTATE).mock(return_value=httpx.Response(200, json=ROTATED))
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, connector, store, settings = make(paired_store(), FakeSettings(BASE))
    await service.rotate(ADMIN, password=PASSWORD)
    until = settings.value.erp_previous_secret_until
    assert until is not None
    assert not await connector.expire_previous_secret(now=until - timedelta(seconds=1))
    assert ERP_WEBHOOK_SECRET_PREVIOUS in store.saved
    assert await connector.expire_previous_secret(now=until + timedelta(seconds=1))
    assert ERP_WEBHOOK_SECRET_PREVIOUS not in store.saved
    assert settings.value.erp_previous_secret_until is None

    # Заданный вручную предыдущий секрет срока не имеет и автоматически не снимается.
    store.saved[ERP_WEBHOOK_SECRET_PREVIOUS] = "manual-previous-secret-for-unit-tests-0001"
    assert not await connector.expire_previous_secret(now=datetime.now(UTC) + timedelta(days=30))
    assert ERP_WEBHOOK_SECRET_PREVIOUS in store.saved


@respx.mock
async def test_successful_check_expires_the_previous_secret() -> None:
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    store = paired_store()
    store.saved[ERP_WEBHOOK_SECRET_PREVIOUS] = OLD_HOOK
    settings = FakeSettings(BASE)
    settings.value = settings.value.model_copy(
        update={"erp_previous_secret_until": datetime.now(UTC) - timedelta(minutes=1)}
    )
    _, connector, store, settings = make(store, settings)
    await connector.check()
    assert ERP_WEBHOOK_SECRET_PREVIOUS not in store.saved


async def test_manual_previous_secret_save_clears_the_auto_expiry_marker() -> None:
    store = paired_store()
    settings = FakeSettings(BASE)
    settings.value = settings.value.model_copy(
        update={"erp_previous_secret_until": datetime.now(UTC) + timedelta(hours=1)}
    )
    _, connector, store, settings = make(store, settings)
    await connector.save(
        ADMIN,
        base_url=BASE,
        service_token=None,
        webhook_secret=None,
        webhook_secret_previous="manual-previous-secret-for-unit-tests-0001",
        password=PASSWORD,
    )
    assert settings.value.erp_previous_secret_until is None


# --- Секреты не светятся --------------------------------------------------------------


def test_generated_secrets_fit_the_contract_and_hide_in_repr() -> None:
    secrets_ = PairingSecrets.generate()
    values = (secrets_.crm_to_erp_token, secrets_.erp_to_crm_token, secrets_.webhook_secret)
    assert len(set(values)) == 3
    for value in values:
        assert 32 <= len(value) <= 512
        assert all(c.isalnum() or c in "-_" for c in value)
        assert value not in repr(secrets_)
        assert value not in str(secrets_)
