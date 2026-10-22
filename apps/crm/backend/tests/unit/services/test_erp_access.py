"""Синхронизация сотрудников с ERP (FIX-11): провижининг и отзыв читают текущее состояние,
ошибки оседают в `erp_sync_error` (лента внешних сервисов), а не в ответе пользователю."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.domain.erp_permissions import ERP_PERMISSIONS
from app.domain.errors import ConflictError, Reason, UpstreamUnavailableError
from app.integrations.erp_users import ProvisionPayload
from app.models.auth import User
from app.services.erp_access import ErpAccessService


class FakeSession:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


class FakeClient:
    def __init__(self, error: Exception | None = None, known: bool = True) -> None:
        self.error = error
        self.known = known
        self.provisioned: list[ProvisionPayload] = []
        self.revoked: list[int] = []

    async def provision_user(self, payload: ProvisionPayload) -> int:
        if self.error:
            raise self.error
        self.provisioned.append(payload)
        return 900

    async def revoke_sessions(self, crm_user_id: int) -> bool:
        if self.error:
            raise self.error
        self.revoked.append(crm_user_id)
        return self.known


def _user(
    *,
    active: bool = True,
    access: list[str] | None = None,
    error: str | None = None,
    erp_roles: list[str] | None = None,
    platform_roles: list[str] | None = None,
) -> User:
    return User(
        id=5,
        email="manager@railtech.uz",
        full_name="Менеджер",
        is_active=active,
        platform_access=access if access is not None else ["crm", "erp"],
        erp_sync_error=error,
        erp_role_codes=erp_roles if erp_roles is not None else [],
        platform_roles=platform_roles if platform_roles is not None else [],
        must_change_password=False,
    )


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"user": _user(), "roles": ["manager"]}

    async def get(session: Any, user_id: int, **_: Any) -> User | None:
        user: User | None = state["user"]
        return user if user is not None and user.id == user_id else None

    async def roles_of(session: Any, user_id: int) -> list[str]:
        roles: list[str] = state["roles"]
        return roles

    async def set_error(session: Any, user_id: int, message: str | None) -> None:
        user: User | None = state["user"]
        if user is not None:
            user.erp_sync_error = message

    monkeypatch.setattr("app.services.erp_access.repo.get", get)
    monkeypatch.setattr("app.services.erp_access.repo.roles_of", roles_of)
    monkeypatch.setattr("app.services.erp_access.repo.set_erp_sync_error", set_error)
    return state


def _service(client: FakeClient) -> ErpAccessService:
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    return ErpAccessService(factory, client)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_provision_sends_role_and_catalog_permissions(wired: dict[str, Any]) -> None:
    client = FakeClient()
    assert await _service(client).provision(5) == "done"

    (payload,) = client.provisioned
    assert (payload.crm_user_id, payload.email, payload.name) == (
        5,
        "manager@railtech.uz",
        "Менеджер",
    )
    assert payload.role == "backoffice"
    assert payload.permissions == ("deal.manage", "quote.build", "quote.edit_pricing", "quote.send")
    assert wired["user"].erp_sync_error is None


@pytest.mark.asyncio
async def test_provision_sends_the_chosen_erp_roles(wired: dict[str, Any]) -> None:
    """FIX-63: роли ERP, выбранные админом, уходят `role_codes` в порядке каталога."""
    wired["user"] = _user(erp_roles=["HEAD", "CALCULATION"])
    client = FakeClient()
    await _service(client).provision(5)
    assert client.provisioned[0].role_codes == ("CALCULATION", "HEAD")


@pytest.mark.asyncio
async def test_provision_without_chosen_roles_sends_an_empty_list(wired: dict[str, Any]) -> None:
    """Ничего не выбрано — `role_codes: []`: ERP снимет ранее выданные из CRM системные роли."""
    client = FakeClient()
    await _service(client).provision(5)
    assert client.provisioned[0].role_codes == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform_role", "role", "role_codes", "permissions"),
    [
        ("MANAGER", "backoffice", ("VIEWER",), ("deal.manage",)),
        ("DIRECTOR", "backoffice", ("HEAD",), ()),
        (
            "SUPPLY",
            "backoffice",
            ("CATALOG_SUPPLY", "FULFILLMENT"),
            ("quote.build", "quote.edit_pricing"),
        ),
        ("ENGINEER", "backoffice", ("FULFILLMENT",), ("quote.build",)),
        ("ACCOUNTANT", "backoffice", ("FINANCE",), ("contract.manage", "fulfillment.act")),
        ("ADMIN", "admin", (), ERP_PERMISSIONS),
    ],
)
async def test_provision_by_platform_role_follows_the_contract_table(
    wired: dict[str, Any],
    platform_role: str,
    role: str,
    role_codes: tuple[str, ...],
    permissions: tuple[str, ...],
) -> None:
    """CRM-01: роль Платформы -> `role_codes` и права поверх шаблонов ролей ERP (не роли CRM)."""
    # Ручные роли в базе игнорируются: при непустых `platform_roles` правит карта контракта.
    wired["user"] = _user(platform_roles=[platform_role], erp_roles=["CALCULATION"])
    wired["roles"] = ["manager"]
    client = FakeClient()

    await _service(client).provision(5)

    (payload,) = client.provisioned
    assert (payload.role, payload.role_codes, payload.permissions) == (
        role,
        role_codes,
        permissions,
    )


@pytest.mark.asyncio
async def test_provision_by_two_platform_roles_is_the_union(wired: dict[str, Any]) -> None:
    wired["user"] = _user(platform_roles=["SUPPLY", "ACCOUNTANT"])
    client = FakeClient()

    await _service(client).provision(5)

    (payload,) = client.provisioned
    assert payload.role == "backoffice"
    assert payload.role_codes == ("CATALOG_SUPPLY", "FULFILLMENT", "FINANCE")
    assert payload.permissions == (
        "quote.build",
        "quote.edit_pricing",
        "contract.manage",
        "fulfillment.act",
    )


@pytest.mark.asyncio
async def test_provision_after_platform_roles_are_removed_returns_to_manual_roles(
    wired: dict[str, Any],
) -> None:
    wired["user"] = _user(platform_roles=[], erp_roles=["VIEWER"])
    wired["roles"] = ["viewer"]
    client = FakeClient()

    await _service(client).provision(5)

    (payload,) = client.provisioned
    assert (payload.role, payload.role_codes, payload.permissions) == (
        "backoffice",
        ("VIEWER",),
        (),
    )


@pytest.mark.asyncio
async def test_provision_of_admin_is_erp_superuser(wired: dict[str, Any]) -> None:
    wired["roles"] = ["admin"]
    client = FakeClient()
    await _service(client).provision(5)
    assert client.provisioned[0].role == "admin"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user",
    [
        pytest.param(None, id="no-such-user"),
        pytest.param(_user(access=["crm"]), id="access-already-revoked"),
        pytest.param(_user(active=False), id="user-deactivated"),
    ],
)
async def test_stale_provision_job_does_nothing(wired: dict[str, Any], user: User | None) -> None:
    """Доступ сняли после постановки задачи: в ERP не создаём того, кому доступ уже не положен."""
    wired["user"] = user
    client = FakeClient()
    assert await _service(client).provision(5) == "skipped"
    assert client.provisioned == []


@pytest.mark.asyncio
async def test_revoke_calls_erp_when_access_is_gone(wired: dict[str, Any]) -> None:
    wired["user"] = _user(access=["crm"])
    client = FakeClient()
    assert await _service(client).revoke(5) == "done"
    assert client.revoked == [5]


@pytest.mark.asyncio
async def test_revoke_for_deactivated_user_with_erp_access_is_sent(wired: dict[str, Any]) -> None:
    wired["user"] = _user(active=False)
    client = FakeClient()
    assert await _service(client).revoke(5) == "done"
    assert client.revoked == [5]


@pytest.mark.asyncio
async def test_stale_revoke_job_never_kills_regranted_access(wired: dict[str, Any]) -> None:
    """Доступ выдали заново после снятия: устаревший отзыв сессий ничего не делает."""
    client = FakeClient()
    assert await _service(client).revoke(5) == "skipped"
    assert client.revoked == []


@pytest.mark.asyncio
async def test_revoke_of_user_unknown_to_erp_is_success_and_clears_error(
    wired: dict[str, Any],
) -> None:
    wired["user"] = _user(access=["crm"], error="erp_provision_user: erp_unavailable: timeout")
    assert await _service(FakeClient(known=False)).revoke(5) == "done"
    assert wired["user"].erp_sync_error is None


@pytest.mark.asyncio
async def test_transient_error_is_recorded_and_raised_for_retry(wired: dict[str, Any]) -> None:
    client = FakeClient(error=UpstreamUnavailableError("timeout", reason=Reason.ERP_UNAVAILABLE))

    with pytest.raises(UpstreamUnavailableError):
        await _service(client).provision(5)

    assert wired["user"].erp_sync_error == "erp_provision_user: erp_unavailable: timeout"


@pytest.mark.asyncio
async def test_unexpected_exception_is_recorded_and_raised_for_retry(wired: dict[str, Any]) -> None:
    with pytest.raises(RuntimeError):
        await _service(FakeClient(error=RuntimeError("boom"))).provision(5)
    assert wired["user"].erp_sync_error == "erp_provision_user: RuntimeError: boom"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["provision", "revoke"])
async def test_not_configured_connector_is_transient_recorded_and_retried(
    wired: dict[str, Any], method: str
) -> None:
    """P1 (FIX-11b): «коннектор не настроен» — повтор по расписанию (админ может подключить ERP
    через минуту), а в `erp_sync_error` — понятный текст с тем, что делать."""
    if method == "revoke":
        wired["user"] = _user(access=["crm"])
    client = FakeClient(
        error=ConflictError("erp connector is not configured", reason=Reason.ERP_NOT_CONFIGURED)
    )

    with pytest.raises(ConflictError):  # пробросили — Procrastinate повторит
        await getattr(_service(client), method)(5)

    task = "erp_provision_user" if method == "provision" else "erp_revoke_sessions"
    error = wired["user"].erp_sync_error
    assert error.startswith(f"{task}: erp_not_configured: ")
    assert "«Подключения»" in error
    assert "повтор" in error


@pytest.mark.asyncio
async def test_permanent_error_is_recorded_and_not_retried(wired: dict[str, Any]) -> None:
    client = FakeClient(error=ConflictError("busy", reason=Reason.ERP_EMAIL_CONFLICT))

    assert (
        await _service(client).provision(5) == "done"
    )  # без исключения — Procrastinate не повторяет

    assert wired["user"].erp_sync_error == "erp_provision_user: erp_email_conflict: busy"


@pytest.mark.asyncio
async def test_error_text_is_bounded(wired: dict[str, Any]) -> None:
    client = FakeClient(error=RuntimeError("x" * 5000))
    with pytest.raises(RuntimeError):
        await _service(client).provision(5)
    assert len(wired["user"].erp_sync_error) <= 500


@pytest.mark.asyncio
async def test_success_clears_previous_error(wired: dict[str, Any]) -> None:
    wired["user"] = _user(error="erp_provision_user: erp_unavailable: timeout")
    await _service(FakeClient()).provision(5)
    assert wired["user"].erp_sync_error is None
