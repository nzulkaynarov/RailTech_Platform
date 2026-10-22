"""Сопряжение CRM ↔ ERP в один клик (M3-CRM-10): «Подключить ERP» и «Обновить ключи».

ERP подменена respx. Проверяется: CRM сама генерирует три секрета и отправляет их под кодом;
сохраняет только после успеха ERP; сразу делает «Проверить связь»; ошибки кода (неверный,
просрочен, использован) — понятные подкоды без изменений в хранилище; пароль админа обязателен;
ротация принимает оба секрета вебхуков заранее и откатывает их при отказе ERP; предыдущий секрет
снимается по истечении перехода; ни кодов, ни токенов в логах, аудите и `repr`.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from app.config import Settings
from app.domain.errors import ConflictError, Reason, UpstreamUnavailableError, ValidationFailedError
from app.integrations.erp import HttpxErpProbe
from app.integrations.erp_pairing import (
    AmbiguousOutcomeError,
    HttpxErpPairingClient,
    PairingSecrets,
)
from app.security import pairing_proof
from app.security.secrets_store import (
    ERP_INBOUND_TOKEN,
    ERP_PENDING_INBOUND_TOKEN,
    ERP_PENDING_SERVICE_TOKEN,
    ERP_PENDING_WEBHOOK_SECRET,
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
OLD_HOOK_CURRENT = OLD_HOOK  # в paired_store это текущий секрет вебхуков
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
    store: FakeStore | None = None,
    settings: FakeSettings | None = None,
    *,
    grace_s: int = 3600,
    config: Settings | None = None,
) -> tuple[ErpPairingService, connector_svc.ErpConnectorService, FakeStore, FakeSettings]:
    store = store or FakeStore()
    settings = settings or FakeSettings()
    config = config or Settings(_env_file=None)
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


@respx.mock
async def test_pair_succeeds_when_the_link_check_is_rate_limited() -> None:
    respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    respx.get(HEALTH).mock(return_value=httpx.Response(429, headers={"Retry-After": "30"}))
    service, _, store, _ = make()
    outcome = await service.pair(ADMIN, base_url=BASE, code=CODE, password=PASSWORD)
    assert outcome.check is None
    assert outcome.check_error == "erp_rate_limited"
    assert outcome.status.paired
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
        httpx.Response(404),
        httpx.Response(422, json={"detail": "VALIDATION_ERROR"}),
        httpx.Response(429, headers={"Retry-After": "30"}),
        httpx.ConnectError("x"),
        httpx.ConnectTimeout("x"),
    ],
)
@respx.mock
async def test_rotate_unambiguous_refusal_rolls_back_and_keeps_old_keys(
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
    respx.post(ROTATE).mock(return_value=httpx.Response(401, json={"detail": "UNAUTHORIZED"}))
    config = Settings(_env_file=None, erp_webhook_secret="env-webhook-secret-unit-test-0001")
    service, _, store, _ = make(
        stored(**{ERP_SERVICE_TOKEN: OLD_TOKEN}), FakeSettings(BASE), config=config
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


# --- Неоднозначный исход «Обновить ключи» --------------------------------------------

PENDING_KEYS = (ERP_PENDING_SERVICE_TOKEN, ERP_PENDING_INBOUND_TOKEN, ERP_PENDING_WEBHOOK_SECRET)


def ambiguous_responses() -> list[httpx.Response | Exception]:
    return [
        httpx.ReadTimeout("erp did not answer"),
        httpx.Response(500),
        httpx.Response(502),
        httpx.Response(503),
        httpx.Response(
            200, json={"rotated": True}
        ),  # ответ непонятен — применила ли ERP, неизвестно
        httpx.ReadError("connection reset"),
    ]


def mock_route(route: respx.Route, response: httpx.Response | Exception) -> None:
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)


@pytest.mark.parametrize("response", ambiguous_responses())
@respx.mock
async def test_rotate_ambiguous_outcome_keeps_pending_triple_and_does_not_roll_back(
    response: httpx.Response | Exception,
) -> None:
    route = respx.post(ROTATE)
    mock_route(route, response)
    service, _, store, settings = make(paired_store(), FakeSettings(BASE))
    with pytest.raises(AmbiguousOutcomeError):
        await service.rotate(ADMIN, password=PASSWORD)
    sent = sent_body(route)
    # ERP могла уже перейти на новые значения: CRM принимает оба секрета вебхуков и помнит тройку.
    assert store.saved[ERP_WEBHOOK_SECRET] == sent["webhook_secret"]
    assert store.saved[ERP_WEBHOOK_SECRET_PREVIOUS] == OLD_HOOK
    assert store.saved[ERP_PENDING_SERVICE_TOKEN] == sent["crm_to_erp_token"]
    assert store.saved[ERP_PENDING_INBOUND_TOKEN] == sent["erp_to_crm_token"]
    assert store.saved[ERP_PENDING_WEBHOOK_SECRET] == sent["webhook_secret"]
    assert store.saved[ERP_SERVICE_TOKEN] == OLD_TOKEN, "рабочий токен меняется только после успеха"
    assert settings.value.erp_previous_secret_until is not None
    status = await service._connector.status()
    assert status.rotation_pending


@respx.mock
async def test_rotate_retry_after_read_timeout_sends_the_same_triple_and_commits() -> None:
    route = respx.post(ROTATE)
    mock_route(route, httpx.ReadTimeout("erp did not answer"))
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, store, _settings = make(paired_store(), FakeSettings(BASE))
    with pytest.raises(AmbiguousOutcomeError):
        await service.rotate(ADMIN, password=PASSWORD)
    first = sent_body(route)

    # ERP на самом деле применила тройку и теперь отвечает идемпотентно — под прежним токеном.
    route.mock(return_value=httpx.Response(200, json=ROTATED))
    outcome = await service.rotate(ADMIN, password=PASSWORD)
    second = sent_body(route)
    assert second == first, "повтор шлёт ту же тройку, а не новую"
    assert route.calls.last.request.headers["authorization"] == f"Bearer {OLD_TOKEN}"
    assert store.saved[ERP_SERVICE_TOKEN] == first["crm_to_erp_token"]
    assert store.saved[ERP_INBOUND_TOKEN] == first["erp_to_crm_token"]
    assert store.saved[ERP_WEBHOOK_SECRET] == first["webhook_secret"]
    assert store.saved[ERP_WEBHOOK_SECRET_PREVIOUS] == OLD_HOOK, "старый секрет не затёрт повтором"
    assert not any(key in store.saved for key in PENDING_KEYS)
    assert not outcome.status.rotation_pending


@respx.mock
async def test_rotate_retry_extends_the_webhook_transition() -> None:
    route = respx.post(ROTATE)
    mock_route(route, httpx.Response(503))
    service, _, _, settings = make(paired_store(), FakeSettings(BASE))
    with pytest.raises(AmbiguousOutcomeError):
        await service.rotate(ADMIN, password=PASSWORD)
    first_until = settings.value.erp_previous_secret_until
    assert first_until is not None
    with pytest.raises(AmbiguousOutcomeError):
        await service.rotate(ADMIN, password=PASSWORD)
    second_until = settings.value.erp_previous_secret_until
    assert second_until is not None
    assert second_until >= first_until


@respx.mock
async def test_rotate_retry_refused_unambiguously_keeps_the_pending_triple() -> None:
    """Откат — только у первой попытки: у повтора прежних значений уже нет, выход — новый код."""
    route = respx.post(ROTATE)
    mock_route(route, httpx.ReadTimeout("x"))
    service, _, store, _ = make(paired_store(), FakeSettings(BASE))
    with pytest.raises(AmbiguousOutcomeError):
        await service.rotate(ADMIN, password=PASSWORD)
    route.mock(return_value=httpx.Response(401, json={"detail": "UNAUTHORIZED"}))
    with pytest.raises(UpstreamUnavailableError):
        await service.rotate(ADMIN, password=PASSWORD)
    assert all(key in store.saved for key in PENDING_KEYS)


@respx.mock
async def test_pairing_again_clears_an_unfinished_rotation() -> None:
    respx.post(ROTATE).mock(side_effect=httpx.ReadTimeout("x"))
    respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, store, _ = make(paired_store(), FakeSettings(BASE))
    with pytest.raises(AmbiguousOutcomeError):
        await service.rotate(ADMIN, password=PASSWORD)
    outcome = await service.pair(ADMIN, base_url=BASE, code=CODE, password=PASSWORD)
    assert not any(key in store.saved for key in PENDING_KEYS)
    assert not outcome.status.rotation_pending


@respx.mock
async def test_pending_rotation_blocks_expiry_of_the_previous_secret() -> None:
    respx.post(ROTATE).mock(side_effect=httpx.ReadTimeout("x"))
    service, connector, store, _settings = make(paired_store(), FakeSettings(BASE))
    with pytest.raises(AmbiguousOutcomeError):
        await service.rotate(ADMIN, password=PASSWORD)
    later = datetime.now(UTC) + timedelta(days=2)
    assert not await connector.expire_previous_secret(now=later)
    assert ERP_WEBHOOK_SECRET_PREVIOUS in store.saved


def test_the_client_tells_clear_refusals_from_ambiguous_outcomes() -> None:
    from app.integrations.erp_pairing import AmbiguousOutcomeError as Ambiguous

    assert issubclass(Ambiguous, UpstreamUnavailableError)


# --- Адрес в проде — только https ------------------------------------------------------


@pytest.mark.parametrize("env", ["prod"])
async def test_prod_requires_https_for_pairing_and_manual_save(env: str) -> None:
    config = Settings(
        _env_file=None,
        app_env=env,
        platform_sso_secret="prod-sso-secret-for-unit-tests-0001",
    )
    service, connector, store, settings = make(config=config)
    with pytest.raises(ValidationFailedError) as caught:
        await service.pair(ADMIN, base_url="http://erp.example", code=CODE, password=PASSWORD)
    assert caught.value.details == {"reason": Reason.ERP_HTTPS_REQUIRED.value, "field": "base_url"}
    with pytest.raises(ValidationFailedError) as caught:
        await connector.save(
            ADMIN,
            base_url="http://erp.example",
            service_token=None,
            webhook_secret=None,
            password=PASSWORD,
        )
    assert caught.value.details == {"reason": Reason.ERP_HTTPS_REQUIRED.value, "field": "base_url"}
    assert store.saved == {}
    assert settings.updates == []


@respx.mock
async def test_prod_accepts_https_and_dev_accepts_http() -> None:
    plain = BASE.replace("https", "http")
    respx.post(ACCEPT.replace(BASE, plain)).mock(return_value=httpx.Response(200, json=ACCEPTED))
    respx.get(HEALTH.replace(BASE, plain)).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, _, settings = make()  # dev
    await service.pair(ADMIN, base_url=plain, code=CODE, password=PASSWORD)
    assert settings.base_url.startswith("http://")


# --- Настройки и ключи — одной транзакцией ---------------------------------------------


@respx.mock
async def test_pair_saves_settings_and_secrets_in_one_transaction() -> None:
    respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, store, settings = make()
    await service.pair(ADMIN, base_url=BASE, code=CODE, password=PASSWORD)
    assert len(set(settings.session_ids)) == 1
    assert set(store.put_sessions) == set(settings.session_ids), "адрес и ключи — одна сессия"
    assert settings.invalidations >= 1


@respx.mock
async def test_rotate_begins_in_one_transaction_with_the_settings_marker() -> None:
    respx.post(ROTATE).mock(side_effect=httpx.ReadTimeout("x"))
    service, _, store, settings = make(paired_store(), FakeSettings(BASE))
    with pytest.raises(AmbiguousOutcomeError):
        await service.rotate(ADMIN, password=PASSWORD)
    assert settings.session_ids[0] in store.put_sessions


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


async def test_previous_secret_is_not_accepted_after_expiry_even_before_any_check() -> None:
    """Приём событий берёт секреты из `resolution`: срок проверяется там, а не из `check()`."""
    store = paired_store()
    older = "older-webhook-secret-for-unit-tests-0002"
    store.saved[ERP_WEBHOOK_SECRET_PREVIOUS] = older
    settings = FakeSettings(BASE)
    soon = datetime.now(UTC) + timedelta(minutes=5)
    settings.value = settings.value.model_copy(update={"erp_previous_secret_until": soon})
    _, connector, _, settings = make(store, settings)
    assert (await connector.resolution()).webhook_secrets == (OLD_HOOK_CURRENT, older)

    settings.value = settings.value.model_copy(
        update={"erp_previous_secret_until": datetime.now(UTC) - timedelta(seconds=1)}
    )
    resolution = await connector.resolution()
    assert resolution.webhook_secrets == (OLD_HOOK_CURRENT,)
    assert resolution.webhook_secret_previous_source == "none"
    assert ERP_WEBHOOK_SECRET_PREVIOUS in store.saved, (
        "строку снимет проверка связи, приём — уже нет"
    )


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


# --- Первое сопряжение без кода (bootstrap, ADR-0009) ---------------------------------

SSO = "unit-test-platform-sso-secret-0001"  # фиктивный общий секрет платформы


def with_sso(**extra: Any) -> Settings:
    return Settings(_env_file=None, platform_sso_secret=SSO, **extra)


def contract_vector() -> dict[str, Any]:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "contracts" / "examples" / "pairing-bootstrap.json"
        if candidate.exists():
            vector: dict[str, Any] = json.loads(candidate.read_text(encoding="utf-8"))
            return vector
    raise AssertionError("pairing-bootstrap.json не найден")


def test_proof_matches_the_contract_test_vector() -> None:
    vector = contract_vector()
    assert vector["label"].encode() == pairing_proof.LABEL == b"rt-pairing-v1"
    header = pairing_proof.sign(
        vector["platform_sso_secret"],
        vector["body"].encode(),
        vector["timestamp"],
        vector["jti"],
    )
    assert header == vector["header"]
    assert pairing_proof.derive_key("x") != b"x", "ключ выводится HKDF, не сам секрет"


@respx.mock
async def test_pair_without_code_uses_bootstrap_proof_and_no_authorization(
    audit_log: list[dict[str, Any]],  # noqa: F811
) -> None:
    accept = respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, store, _ = make(config=with_sso())
    with capture_logs() as logs:
        outcome = await service.pair(ADMIN, base_url=BASE, code=None, password=PASSWORD)
    request = accept.calls.last.request
    assert "authorization" not in request.headers, "без кода ERP получает доказательство, не токен"
    header = request.headers["x-pairing-proof"]
    version, ts, jti, digest = header.split(".")
    assert version == "v1"
    assert abs(int(ts) - datetime.now(UTC).timestamp()) < 60
    # Доказательство покрывает ровно отправленное тело (его хеш) и считается ключом HKDF.
    assert header == pairing_proof.sign(SSO, request.content, int(ts), jti)
    body = json.loads(request.content)
    assert store.saved[ERP_SERVICE_TOKEN] == body["crm_to_erp_token"]
    assert outcome.status.paired
    assert outcome.check is not None
    assert [r["after"]["method"] for r in audit_log if "after" in r and "method" in r["after"]] == [
        "bootstrap"
    ]
    dump = json.dumps([logs, audit_log], default=str)
    for secret in (SSO, header, jti, digest, *body.values()):
        assert secret not in dump


@respx.mock
async def test_pair_with_code_ignores_bootstrap_even_if_the_secret_exists(
    audit_log: list[dict[str, Any]],  # noqa: F811
) -> None:
    accept = respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    service, _, _, _ = make(config=with_sso())
    await service.pair(ADMIN, base_url=BASE, code=CODE, password=PASSWORD)
    request = accept.calls.last.request
    assert request.headers["authorization"] == f"Bearer {CODE}"
    assert "x-pairing-proof" not in request.headers
    assert [r["after"]["method"] for r in audit_log if "after" in r and "method" in r["after"]] == [
        "code"
    ]


@pytest.mark.parametrize(
    "detail", ["PAIRING_PROOF_INVALID", "PAIRING_PROOF_EXPIRED", "PAIRING_PROOF_REPLAYED"]
)
@respx.mock
async def test_bootstrap_rejected_proof_is_explained_and_changes_nothing(detail: str) -> None:
    respx.post(ACCEPT).mock(return_value=httpx.Response(401, json={"detail": detail}))
    service, _, store, settings = make(config=with_sso())
    with pytest.raises(ValidationFailedError) as caught:
        await service.pair(ADMIN, base_url=BASE, code=None, password=PASSWORD)
    assert caught.value.details == {"reason": Reason.ERP_BOOTSTRAP_REJECTED.value, "field": "code"}
    assert store.saved == {}
    assert settings.updates == []


@respx.mock
async def test_bootstrap_closed_window_asks_for_a_code() -> None:
    respx.post(ACCEPT).mock(return_value=httpx.Response(409, json={"detail": "BOOTSTRAP_CLOSED"}))
    service, _, store, _ = make(config=with_sso())
    with pytest.raises(ValidationFailedError) as caught:
        await service.pair(ADMIN, base_url=BASE, code=None, password=PASSWORD)
    assert caught.value.details == {"reason": Reason.ERP_BOOTSTRAP_CLOSED.value, "field": "code"}
    assert store.saved == {}


@respx.mock
async def test_no_code_and_no_shared_secret_is_explained_without_calling_erp() -> None:
    route = respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    service, _, _, _ = make()  # платформенного секрета нет
    with pytest.raises(ValidationFailedError) as caught:
        await service.pair(ADMIN, base_url=BASE, code="  ", password=PASSWORD)
    assert caught.value.details == {
        "reason": Reason.ERP_BOOTSTRAP_UNAVAILABLE.value,
        "field": "code",
    }
    assert not route.called


@respx.mock
async def test_bootstrap_on_an_old_erp_is_unsupported_and_5xx_is_ambiguous() -> None:
    route = respx.post(ACCEPT).mock(return_value=httpx.Response(404))
    service, _, _, _ = make(config=with_sso())
    with pytest.raises(UpstreamUnavailableError) as caught:
        await service.pair(ADMIN, base_url=BASE, code=None, password=PASSWORD)
    assert caught.value.details["reason"] == Reason.ERP_PAIRING_UNSUPPORTED.value
    route.mock(return_value=httpx.Response(503))
    with pytest.raises(AmbiguousOutcomeError):
        await service.pair(ADMIN, base_url=BASE, code=None, password=PASSWORD)


@respx.mock
async def test_bootstrap_never_runs_by_itself() -> None:
    """Только по кнопке: проверка связи и состояние вызовов сопряжения не делают."""
    route = respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    respx.get(HEALTH).mock(return_value=httpx.Response(401))
    _, connector, _, _ = make(paired_store(), FakeSettings(BASE), config=with_sso())
    await connector.status()
    await connector.health_facts()
    with pytest.raises(UpstreamUnavailableError):
        await connector.check()
    assert not route.called


async def test_status_suggests_the_internal_address_and_tells_if_bootstrap_is_available() -> None:
    _, connector, _, _ = make(config=with_sso())
    status = await connector.status()
    assert status.suggested_base_url == "http://erp-backend:8000"
    assert status.bootstrap_available
    _, plain, _, _ = make()
    assert not (await plain.status()).bootstrap_available


# --- http допустим только внутри сети; внешний адрес — https ----------------------------


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("http://erp-backend:8000", True),
        ("http://localhost:8000", True),
        ("http://10.0.0.3:8000", True),
        ("http://172.20.1.5", True),
        ("http://192.168.1.10:8000", True),
        ("http://127.0.0.1:8000", True),
        ("https://erp.railtech.uz", True),
        ("https://93.184.216.34", True),
        ("http://erp.railtech.uz", False),
        ("http://93.184.216.34:8000", False),
        ("http://8.8.8.8", False),
        ("http://erp.internal.example", False),
    ],
)
def test_requires_https_only_for_public_hosts(url: str, allowed: bool) -> None:
    from app.domain.erp_connector import requires_https

    assert requires_https(url) is (not allowed)


@pytest.mark.parametrize("url", ["http://erp.railtech.uz", "http://93.184.216.34:8000"])
async def test_prod_rejects_http_to_a_public_address_for_code_and_bootstrap(url: str) -> None:
    service, _connector, store, _ = make(config=with_sso(app_env="prod"))
    for code in (CODE, None):
        with pytest.raises(ValidationFailedError) as caught:
            await service.pair(ADMIN, base_url=url, code=code, password=PASSWORD)
        assert caught.value.details["reason"] == Reason.ERP_HTTPS_REQUIRED.value
    assert store.saved == {}


@pytest.mark.parametrize("url", ["http://erp-backend:8000", "http://10.0.0.3:8000"])
@respx.mock
async def test_prod_allows_http_inside_the_network(url: str) -> None:
    respx.post(url + "/api/integration/v1/pairing/accept").mock(
        return_value=httpx.Response(200, json=ACCEPTED)
    )
    respx.get(url + "/api/integration/v1/health").mock(
        return_value=httpx.Response(200, json=HEALTHY)
    )
    service, _, _store, settings = make(config=with_sso(app_env="prod"))
    outcome = await service.pair(ADMIN, base_url=url, code=None, password=PASSWORD)
    assert outcome.status.paired
    assert settings.base_url == url
