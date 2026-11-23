"""Вход, выход, сессия и смена пароля.

Контракт: tag `auth`; устройство — docs/architecture/platform-bff.md §3.
"""

import structlog
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from app.auth import FAILED_LOGIN_CODES, SecondFactorChallenge
from app.client_ip import UNKNOWN
from app.clients import crm_setup
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
from app.schemas import (
    ChangePasswordIn,
    EnrolledSession,
    EnrollIn,
    EnrollSetupIn,
    LoginIn,
    SecondFactorChallengeOut,
    SecondFactorLoginIn,
    SessionOut,
    build_session,
)
from app.schemas_profile import (
    ForgotPasswordAccepted,
    ForgotPasswordIn,
    ResetPasswordIn,
    SecondFactorSetup,
)
from app.session import SessionData

router = APIRouter(tags=["auth"])
log = structlog.get_logger()


# Метка «запомнить устройство» после второго фактора (ДВ-4): выдаёт и проверяет CRM, BFF хранит.
DEVICE_COOKIE = "pf_device"
DEVICE_COOKIE_PATH = "/api/v1/auth"
DEVICE_MAX_AGE = 30 * 86400


@router.post(
    "/auth/login",
    response_model=SessionOut,
    responses={202: {"model": SecondFactorChallengeOut}},
    operation_id="login",
)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    limiter: LoginLimiterDep,
    settings: SettingsDep,
) -> SessionOut | JSONResponse:
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
        result = await service.login(
            email,
            body.password,
            None if ip == UNKNOWN else ip,
            request.cookies.get(DEVICE_COOKIE),
        )
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
    if isinstance(result, SecondFactorChallenge):
        log.info("login_second_factor_required", email_hash=attempt.email_digest[:12])
        return JSONResponse(
            SecondFactorChallengeOut(
                challenge=result.challenge, enrollment_required=result.enrollment
            ).model_dump(),
            status_code=status.HTTP_202_ACCEPTED,
            headers={"Cache-Control": "no-store"},
        )
    sid, data = result
    log.info("login_succeeded", user_id=data.user_id)
    return await _signed_in(request, response, service, settings, sid, data)


@router.post(
    "/auth/login/second-factor", response_model=SessionOut, operation_id="loginSecondFactor"
)
async def login_second_factor(
    body: SecondFactorLoginIn,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    limiter: LoginLimiterDep,
    settings: SettingsDep,
) -> SessionOut:
    """Код приложения-аутентификатора или резервный код после пароля (ДВ-4). Неверные коды
    считает и блокирует CRM; здесь — тот же лимит попыток по IP, что у входа."""
    ip: str = request.state.client_ip
    attempt = await limiter.check(ip, "second-factor")
    try:
        sid, data, device = await service.second_factor(
            body.challenge, body.code, body.remember_device, None if ip == UNKNOWN else ip
        )
    except PlatformError as exc:
        log.warning("login_second_factor_failed", code=exc.body.code, status=exc.status_code)
        if exc.body.code not in FAILED_LOGIN_CODES:
            await limiter.refund(attempt)
        raise
    except Exception:
        await limiter.refund(attempt)
        raise
    await limiter.succeeded(attempt)
    log.info("login_succeeded", user_id=data.user_id, second_factor=True)
    if device:
        response.set_cookie(
            DEVICE_COOKIE,
            device,
            max_age=DEVICE_MAX_AGE,
            path=DEVICE_COOKIE_PATH,
            secure=settings.cookie_secure,
            httponly=True,
            samesite="strict",
        )
    return await _signed_in(request, response, service, settings, sid, data)


@router.post(
    "/auth/login/enroll/setup",
    response_model=SecondFactorSetup,
    operation_id="loginEnrollSetup",
)
async def login_enroll_setup(
    body: EnrollSetupIn, request: Request, service: AuthServiceDep, limiter: LoginLimiterDep
) -> SecondFactorSetup:
    """Секрет и адрес QR при входе, когда фактор обязателен по разделам доступа, но не настроен
    (ДВ-4б): `challenge` из 202 на `/auth/login` с `enrollment_required`."""
    ip: str = request.state.client_ip
    attempt = await limiter.check(ip, "second-factor")
    try:
        try:
            issuer = (await crm_setup.fetch_state(request.app.state.crm)).company_name or ""
        except (BackendUnavailableError, PlatformError):
            issuer = ""
        setup = await service.enroll_setup(
            body.challenge, issuer[:60], None if ip == UNKNOWN else ip
        )
    except BaseException:
        await limiter.refund(attempt)
        raise
    await limiter.succeeded(attempt)
    return SecondFactorSetup.model_validate(setup)


@router.post("/auth/login/enroll", response_model=EnrolledSession, operation_id="loginEnroll")
async def login_enroll(
    body: EnrollIn,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    limiter: LoginLimiterDep,
    settings: SettingsDep,
) -> EnrolledSession:
    """Код из приложения включает фактор и открывает сессию; резервные коды — в ответе, один раз
    (ДВ-4б). Неверный код — 401 `SECOND_FACTOR_INVALID` (в счёт блокировки CRM), время вышло —
    401 `SECOND_FACTOR_EXPIRED`."""
    ip: str = request.state.client_ip
    attempt = await limiter.check(ip, "second-factor")
    try:
        sid, data, codes = await service.enroll(
            body.challenge, body.code, None if ip == UNKNOWN else ip
        )
    except PlatformError as exc:
        log.warning("login_enroll_failed", code=exc.body.code, status=exc.status_code)
        if exc.body.code not in FAILED_LOGIN_CODES:
            await limiter.refund(attempt)
        raise
    except Exception:
        await limiter.refund(attempt)
        raise
    await limiter.succeeded(attempt)
    log.info("login_succeeded", user_id=data.user_id, second_factor="enrolled")
    session = await _signed_in(request, response, service, settings, sid, data)
    response.headers["Cache-Control"] = "no-store"
    return EnrolledSession(**session.model_dump(), backup_codes=codes)


async def _signed_in(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    sid: str,
    data: SessionData,
) -> SessionOut:
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
