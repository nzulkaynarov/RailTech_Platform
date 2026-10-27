"""Первый запуск и временные пароли (W13-A4, контракт BFF 0.10.0).

CRM: `/api/v1/setup/state` и `/setup/admin` (без токена: сотрудника ещё нет), `/setup/checklist`,
`/integrations/erp`, `/integrations/smtp`, `/users*` (с токеном администратора).
ERP: `setup/status/` и `setup/company/` токеном администратора.
Решает бэкенд (код первого запуска, пароль, право, «компания уже есть»); здесь — вызовы, разбор
ответов моделями CRM и перевод ошибок в формат `Error`.

Временный пароль проходит через этот модуль один раз — из ответа CRM в ответ BFF. Он не попадает в
журнал, ошибки, кэш и сессию: функции возвращают его вызывающему и ничего не запоминают.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.clients import crm_models as crm
from app.clients.base import BackendUnavailableError, cookie_value
from app.clients.crm import REFRESH_COOKIE, CrmClient
from app.errors import (
    PlatformError,
    backend_reason,
    backend_unavailable,
    from_backend,
)
from app.schemas_setup import (
    STEP_KEYS,
    CompanyBlocker,
    SetupChecklist,
    SetupCompanyStatus,
    SetupStep,
)

Call = Callable[..., Awaitable[httpx.Response]]

SETUP = "/api/v1/setup"
SETUP_LOCK_SECONDS = 15 * 60

CODE_INVALID_MESSAGE = "Код неверный. Скопируйте его из журнала сервера (crm-api) без изменений."
CODE_EXPIRED_MESSAGE = (
    "Код устарел. Откройте /setup заново: система выдаст новый код в журнале сервера."
)
LOCKED_MESSAGE = "Слишком много неверных кодов. Повторите через 15 минут."
SETUP_DONE_MESSAGE = "Администратор уже создан. Войдите в Платформу."
COMPANY_EXISTS_MESSAGE = "Своя компания уже создана."
COMPANY_FORBIDDEN_MESSAGE = "Создать свою компанию может только администратор ERP."
ERP_NOT_CONNECTED_MESSAGE = (
    "ERP не подключена. Сначала подключите ERP (Администрирование — Внешние интеграции — ERP), "
    "затем создайте компанию."
)

# Поле CRM -> поле контракта (`details.fields`).
_SETUP_FIELDS = {"full_name": "name", "code": "code", "email": "email", "password": "password"}


class ErpSetupStatus(BaseModel):
    setup_required: bool
    can_setup: bool


class ErpCompanyCreated(BaseModel):
    id: int
    name: str


def _details(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    details = body.get("details") if isinstance(body, dict) else None
    return details if isinstance(details, dict) else {}


def setup_error(response: httpx.Response) -> PlatformError:
    """Отказ CRM на `/setup/admin` -> код контракта. Остальное решает общий перевод."""
    status = response.status_code
    reason = backend_reason(response)
    base = from_backend("crm", response)
    if status == 409 and reason == "setup_done":
        return PlatformError(
            "SETUP_DONE",
            SETUP_DONE_MESSAGE,
            status_code=409,
            source="crm",
            details={"reason": reason},
        )
    if status == 422 and reason == "setup_code_invalid":
        return PlatformError(
            "SETUP_CODE_INVALID",
            CODE_INVALID_MESSAGE,
            status_code=422,
            source="crm",
            details={"reason": reason, "fields": ["code"]},
        )
    if status == 422 and reason == "setup_code_expired":
        return PlatformError(
            "SETUP_CODE_EXPIRED",
            CODE_EXPIRED_MESSAGE,
            status_code=422,
            source="crm",
            details={"reason": reason, "fields": ["code"]},
        )
    if status == 422 and reason == "setup_locked":
        return PlatformError(
            "SETUP_LOCKED",
            LOCKED_MESSAGE,
            status_code=429,
            source="crm",
            details={"reason": reason, "fields": ["code"]},
            headers={"Retry-After": str(SETUP_LOCK_SECONDS)},
        )
    if status == 422:
        details = _details(response)
        names = [e.get("field") for e in details.get("errors") or [] if isinstance(e, dict)]
        names.append(details.get("field"))
        fields = sorted({_SETUP_FIELDS.get(str(n), str(n)) for n in names if n})
        extra: dict[str, Any] = {"fields": fields} if fields else {}
        if reason:
            extra["reason"] = reason
        base.body.details = {**(base.body.details or {}), **extra}
    return base


async def fetch_state(client: CrmClient) -> bool:
    """`True` — администратора ещё нет (нужен экран «Первый запуск»). Без токена."""
    try:
        response = await client.send("GET", f"{SETUP}/state")
    except BackendUnavailableError as exc:
        raise backend_unavailable("crm", exc.reason) from exc
    if response.status_code != 200:
        raise from_backend("crm", response)
    try:
        return crm.SetupState.model_validate(response.json()).needs_setup
    except (ValueError, ValidationError) as exc:
        raise backend_unavailable("crm", "bad_setup_state") from exc


async def create_admin(
    client: CrmClient, payload: dict[str, str], client_ip: str | None
) -> str | None:
    """Создать первого администратора. Возвращает refresh-токен семьи, которую CRM открыла при
    входе после создания: вызывающий её гасит (сессию Платформы открывает обычный вход)."""
    try:
        response = await client.send(
            "POST",
            f"{SETUP}/admin",
            json=payload,
            headers={"X-Forwarded-For": client_ip} if client_ip else None,
        )
    except BackendUnavailableError as exc:
        raise backend_unavailable("crm", exc.reason) from exc
    if response.status_code != 200:
        raise setup_error(response)
    return cookie_value(response, REFRESH_COOKIE)


# --- чек-лист -----------------------------------------------------------------------------------


async def _get(call: Call, backend: str, path: str) -> Any | None:
    """JSON ответа 200 или `None`: бэкенд не ответил, отказал или нет права — шаг `unknown`.
    Истёкшая сессия (401) не «неизвестность» — она идёт наружу."""
    try:
        response = await call(backend, "GET", path)
    except PlatformError as exc:
        if exc.status_code == 401:
            raise
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _parse[T: BaseModel](model: type[T], raw: Any | None) -> T | None:
    if raw is None:
        return None
    try:
        return model.model_validate(raw)
    except ValidationError:
        return None


def _state(done: bool | None) -> str:
    if done is None:
        return "unknown"
    return "done" if done else "todo"


def _crm_item_done(checklist: crm.SetupChecklist | None, key: str) -> bool | None:
    if checklist is None:
        return None
    item = next((i for i in checklist.items if i.key.value == key), None)
    return None if item is None else item.done


async def build_checklist(call: Call) -> SetupChecklist:
    """Свод состояния пяти шагов и шага «своя компания». BFF не оценивает: все пять шагов приносит
    CRM `/setup/checklist` (W13C-F1, Q-W13-A4-2: ключи `bot`, `erp`, `mail`, `models`,
    `first_employee`). Что CRM не отдала — `unknown`; CRM не ответила совсем — 503.

    Шаг «своя компания» спрашивает ERP только когда ERP сопряжена: без сопряжения вызов ERP
    бесполезен (сессии ERP у администратора нет), а ожидание — тупик. Причина отсутствия данных
    о компании — `company_blocker`: `erp_not_connected` (сначала подключите ERP) или
    `erp_unavailable` (ERP не ответила)."""
    checklist_raw = await _get(call, "crm", f"{SETUP}/checklist")
    checklist = _parse(crm.SetupChecklist, checklist_raw)
    if checklist is None:
        raise backend_unavailable("crm", "setup_checklist")
    facts: dict[str, bool | None] = {key: _crm_item_done(checklist, key) for key in STEP_KEYS}
    steps = [SetupStep(key=key, state=_state(facts[key])) for key in STEP_KEYS]
    company: SetupCompanyStatus | None = None
    blocker: CompanyBlocker | None = None
    if facts["erp"] is False:
        blocker = "erp_not_connected"
    else:
        status = _parse(ErpSetupStatus, await _get(call, "erp", "/api/v1/setup/status/"))
        if status is None:
            blocker = "erp_unavailable"
        else:
            company = SetupCompanyStatus(required=status.setup_required, can_setup=status.can_setup)
    return SetupChecklist(
        steps=steps,
        done=sum(1 for s in steps if s.state == "done"),
        total=len(steps),
        company=company,
        company_blocker=blocker,
    )


# --- своя компания (ERP) ------------------------------------------------------------------------


def company_error(response: httpx.Response) -> PlatformError:
    """Отказ ERP `setup/company/` -> код контракта."""
    status = response.status_code
    base = from_backend("erp", response)
    if status == 403:
        base.body.message = COMPANY_FORBIDDEN_MESSAGE
        return base
    if status == 409:
        return PlatformError(
            "OWN_COMPANY_ALREADY_EXISTS",
            COMPANY_EXISTS_MESSAGE,
            status_code=409,
            source="erp",
            details={"backend_status": 409},
        )
    if status == 422:
        try:
            body = response.json()
        except ValueError:
            body = None
        fields: list[str] = []
        messages: dict[str, str] = {}
        if isinstance(body, dict):
            for name, problem in body.items():
                fields.append(str(name))
                first = problem[0] if isinstance(problem, list) and problem else problem
                if isinstance(first, str):
                    messages[str(name)] = first
        base.body.details = {
            **(base.body.details or {}),
            "fields": sorted(fields),
            "messages": messages,
        }
    return base


async def ensure_erp_connected(call: Call) -> None:
    """409 `ERP_NOT_CONNECTED`, если CRM знает, что коннектор ERP не задан (сопряжения нет).

    CRM не ответила или не отдала состояние — не блокируем: решает сама ERP (503 или ответ)."""
    status = _parse(crm.ErpStatusOut, await _get(call, "crm", "/api/v1/integrations/erp"))
    if status is not None and not status.configured:
        raise PlatformError(
            "ERP_NOT_CONNECTED",
            ERP_NOT_CONNECTED_MESSAGE,
            status_code=409,
            source="bff",
            details={"reason": "erp_not_connected", "link": "/admin/integrations?card=erp"},
        )


async def create_company(call: Call, payload: dict[str, Any]) -> ErpCompanyCreated:
    await ensure_erp_connected(call)
    response = await call("erp", "POST", "/api/v1/setup/company/", json=payload)
    if response.status_code != 201:
        raise company_error(response)
    created = _parse(ErpCompanyCreated, _safe_json(response))
    if created is None:
        raise backend_unavailable("erp", "bad_company_response")
    return created


def _safe_json(response: httpx.Response) -> Any | None:
    try:
        return response.json()
    except ValueError:
        return None


# --- временный пароль (без почты) ---------------------------------------------------------------


async def create_user_with_password(
    call: Call, payload: dict[str, Any], failure: Callable[[httpx.Response], PlatformError]
) -> tuple[dict[str, Any], str]:
    """`POST /users` CRM: пользователь и временный пароль «показывается один раз»."""
    response = await call("crm", "POST", "/api/v1/users", json=payload)
    if response.status_code != 201:
        raise failure(response)
    body = _safe_json(response)
    if not isinstance(body, dict) or not isinstance(body.get("user"), dict):
        raise backend_unavailable("crm", "bad_user_response")
    password = body.get("temporary_password")
    if not isinstance(password, str) or not password:
        raise backend_unavailable("crm", "no_temporary_password")
    user: dict[str, Any] = body["user"]
    return user, password


async def reset_user_password(
    call: Call, user_id: str, failure: Callable[[httpx.Response], PlatformError]
) -> str:
    """`POST /users/{id}/reset-password` CRM: новый временный пароль, прежний и сессии сотрудника
    перестают действовать; почта не нужна."""
    response = await call("crm", "POST", f"/api/v1/users/{user_id}/reset-password")
    if response.status_code != 200:
        raise failure(response)
    reset = _parse(crm.PasswordReset, _safe_json(response))
    if reset is None or not reset.temporary_password:
        raise backend_unavailable("crm", "no_temporary_password")
    return reset.temporary_password
