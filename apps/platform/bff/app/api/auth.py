"""Вход, выход, сессия и смена пароля.

Контракт: tag `auth`; устройство — docs/architecture/platform-bff.md §3.
"""

import structlog
from fastapi import APIRouter, Request, Response, status

from app.auth import FAILED_LOGIN_CODES
from app.client_ip import UNKNOWN
from app.cookies import SESSION_COOKIE, clear_session_cookies, set_session_cookies
from app.deps import AuthedDep, AuthServiceDep, LoginLimiterDep, SettingsDep
from app.errors import PlatformError
from app.schemas import ChangePasswordIn, LoginIn, SessionOut, build_session

router = APIRouter(tags=["auth"])
log = structlog.get_logger()


@router.post("/auth/login", response_model=SessionOut, operation_id="login")
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    limiter: LoginLimiterDep,
    settings: SettingsDep,
) -> SessionOut:
    email = body.email.strip()
    # Адрес клиента (X-Forwarded-For от доверенного Caddy) определяет ClientIpMiddleware,
    # он же стоит в каждой записи журнала.
    ip: str = request.state.client_ip
    try:
        attempt = await limiter.check(ip, email)
    except PlatformError:
        log.warning("login_rate_limited")
        raise
    try:
        sid, data = await service.login(email, body.password, None if ip == UNKNOWN else ip)
    except PlatformError as exc:
        counted = exc.body.code in FAILED_LOGIN_CODES
        log.warning(
            "login_failed" if counted else "login_not_completed",
            code=exc.body.code,
            status=exc.status_code,
            email_hash=attempt.email_digest[:12],
        )
        if not counted:
            await limiter.refund(attempt)
        raise
    except Exception:
        await limiter.refund(attempt)
        raise
    await limiter.succeeded(attempt)
    log.info("login_succeeded", user_id=data.user_id)
    set_session_cookies(
        response,
        sid=sid,
        csrf=data.csrf,
        max_age=settings.session_ttl_hours * 3600,
        secure=settings.cookie_secure,
    )
    previous = request.cookies.get(SESSION_COOKIE)
    if previous and previous != sid:
        # Повторный вход поверх старой сессии: старая закрывается, чтобы не висели токены.
        await service.logout(previous)
    return build_session(data)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="logout")
async def logout(authed: AuthedDep, settings: SettingsDep) -> Response:
    await authed.service.logout(authed.sid)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(response, secure=settings.cookie_secure)
    return response


@router.post(
    "/auth/change-password", status_code=status.HTTP_204_NO_CONTENT, operation_id="changePassword"
)
async def change_password(body: ChangePasswordIn, authed: AuthedDep) -> Response:
    await authed.service.change_password(authed.sid, body.current_password, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/session", response_model=SessionOut, operation_id="getSession")
async def get_session(authed: AuthedDep) -> SessionOut:
    data = await authed.service.sync_profile(authed.sid, authed.data)
    return build_session(data)
