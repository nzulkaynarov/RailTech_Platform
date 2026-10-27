"""Вход, выход, сессия и смена пароля.

Контракт: tag `auth`; устройство — docs/architecture/platform-bff.md §3.
"""

import structlog
from fastapi import APIRouter, Request, Response, status

from app.auth import FAILED_LOGIN_CODES
from app.client_ip import UNKNOWN
from app.clients.base import BackendUnavailableError
from app.cookies import SESSION_COOKIE, clear_session_cookies, set_session_cookies
from app.deps import (
    AuthedDep,
    AuthServiceDep,
    CrmDep,
    ForgotLimiterDep,
    LoginLimiterDep,
    ResetLimiterDep,
    SettingsDep,
)
from app.errors import PlatformError, backend_reason, backend_unavailable, from_backend
from app.schemas import ChangePasswordIn, LoginIn, SessionOut, build_session
from app.schemas_profile import ForgotPasswordAccepted, ForgotPasswordIn, ResetPasswordIn

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


@router.post(
    "/auth/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ForgotPasswordAccepted,
    operation_id="forgotPassword",
)
async def forgot_password(
    body: ForgotPasswordIn,
    request: Request,
    crm: CrmDep,
    limiter: ForgotLimiterDep,
) -> ForgotPasswordAccepted:
    """«Забыли пароль?»: ответ один для любой учётной записи, счётчик расходуется всегда."""
    await limiter.check(request.state.client_ip, body.identifier)
    try:
        response = await crm.forgot_password(body.identifier.strip())
    except BackendUnavailableError as exc:
        raise backend_unavailable("crm", exc.reason) from exc
    if response.status_code >= 400:
        # Отказ CRM по существу наружу не пробрасываем: иначе ответ различал бы учётные записи.
        log.warning("forgot_password_refused", status=response.status_code)
    return ForgotPasswordAccepted()


@router.post(
    "/auth/reset-password", status_code=status.HTTP_204_NO_CONTENT, operation_id="resetPassword"
)
async def reset_password(
    body: ResetPasswordIn, request: Request, crm: CrmDep, limiter: ResetLimiterDep
) -> Response:
    await limiter.check(request.state.client_ip)
    try:
        response = await crm.reset_password(body.token, body.new_password)
    except BackendUnavailableError as exc:
        raise backend_unavailable("crm", exc.reason) from exc
    if response.status_code == status.HTTP_204_NO_CONTENT:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    reason = backend_reason(response)
    if response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT and reason in (
        "reset_token_invalid",
        "weak_password",
    ):
        field = "token" if reason == "reset_token_invalid" else "new_password"
        message = (
            "Ссылка недействительна или устарела. Запросите новую."
            if field == "token"
            else "Пароль слишком простой: нужно не меньше 10 символов, буквы и цифры."
        )
        raise PlatformError(
            "VALIDATION_FAILED",
            message,
            status_code=422,
            source="crm",
            details={"fields": [field], "reason": reason},
        )
    raise from_backend("crm", response)
