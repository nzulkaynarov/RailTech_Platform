"""Первый запуск: администратор без сессии, чек-лист и своя компания (tag `setup`, 0.10.0).

BFF не решает: код первого запуска, пароль и «администратор уже есть» проверяет CRM, право на
создание компании — ERP. Здесь — вызовы, свод состояния шагов и открытие сессии Платформы под
созданным администратором теми же cookie, что при входе.
"""

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Request, Response, status

from app.client_ip import UNKNOWN
from app.clients import crm_setup
from app.cookies import set_session_cookies
from app.deps import Authed, AuthServiceDep, LoginLimiterDep, SettingsDep, require
from app.errors import PlatformError
from app.schemas import SessionOut, build_session
from app.schemas_setup import (
    SetupAdminIn,
    SetupChecklist,
    SetupCompanyCreated,
    SetupCompanyIn,
    SetupState,
)

router = APIRouter(tags=["setup"])
log = structlog.get_logger()

Admin = Annotated[Authed, Depends(require("admin", "full"))]

# Неверный или заблокированный код — перебор: попытка остаётся в лимите входа. Остальные отказы
# (слабый пароль, администратор уже есть, сбой CRM) лимит не расходуют.
_COUNTED = frozenset({"SETUP_CODE_INVALID", "SETUP_LOCKED"})


@router.get("/setup/state", response_model=SetupState, operation_id="getSetupState")
async def get_setup_state(request: Request, response: Response) -> SetupState:
    needs = await crm_setup.fetch_state(request.app.state.crm)
    response.headers["Cache-Control"] = "no-store"
    return SetupState(needs_admin=needs)


@router.post("/setup/admin", response_model=SessionOut, operation_id="createFirstAdmin")
async def create_first_admin(
    body: SetupAdminIn,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    limiter: LoginLimiterDep,
    settings: SettingsDep,
) -> SessionOut:
    email = body.email.strip()
    ip: str = request.state.client_ip
    client_ip = None if ip == UNKNOWN else ip
    attempt = await limiter.check(ip, email)
    payload = {
        "code": body.code.get_secret_value(),
        "email": email,
        "full_name": body.name,
        "password": body.password.get_secret_value(),
    }
    try:
        refresh = await crm_setup.create_admin(service.crm, payload, client_ip)
    except PlatformError as exc:
        log.warning("setup_admin_failed", code=exc.body.code, status=exc.status_code)
        if exc.body.code not in _COUNTED:
            await limiter.refund(attempt)
        raise
    except Exception:
        await limiter.refund(attempt)
        raise
    # CRM после создания вошла сама и выдала refresh-токен; сессию Платформы открывает обычный
    # вход (роли, доступ к ERP), поэтому токен CRM не нужен и не должен висеть.
    if refresh:
        await service.crm.logout(refresh)
    try:
        sid, data = await service.login(email, body.password.get_secret_value(), client_ip)
    except BaseException:
        await limiter.refund(attempt)
        raise
    await limiter.succeeded(attempt)
    log.info("setup_admin_created", user_id=data.user_id)
    set_session_cookies(
        response,
        sid=sid,
        csrf=data.csrf,
        max_age=settings.session_ttl_hours * 3600,
        secure=settings.cookie_secure,
    )
    return build_session(data)


@router.get("/setup/checklist", response_model=SetupChecklist, operation_id="getSetupChecklist")
async def get_setup_checklist(authed: Admin, response: Response) -> SetupChecklist:
    response.headers["Cache-Control"] = "no-store"
    return await crm_setup.build_checklist(authed.call)


@router.post(
    "/setup/company",
    response_model=SetupCompanyCreated,
    status_code=status.HTTP_201_CREATED,
    operation_id="createOwnCompany",
)
async def create_own_company(body: SetupCompanyIn, authed: Admin) -> SetupCompanyCreated:
    payload: dict[str, Any] = {"name": body.name}
    for field in ("inn", "legal_address", "phone", "email"):
        value = getattr(body, field)
        if value is not None and value.strip():
            payload[field] = value.strip()
    created = await crm_setup.create_company(authed.call, payload)
    return SetupCompanyCreated(id=created.id, name=created.name)
