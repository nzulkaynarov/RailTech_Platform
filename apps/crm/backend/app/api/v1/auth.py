"""Аутентификация (SPEC §11): access в теле ответа, refresh — httpOnly cookie с ротацией."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import ContainerDep, PrincipalDep, client_ip
from app.config import Settings
from app.domain.errors import AuthError
from app.schemas.auth import (
    ChangePasswordRequest,
    EnrollRequest,
    EnrollSetupRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    SecondFactorChallengeResponse,
    SecondFactorLoginRequest,
    SecondFactorSetupResponse,
    SsoTokenRequest,
    SsoTokenResponse,
    TokenResponse,
)
from app.services.auth import ClientInfo, EnrollmentRequired, SecondFactorRequired, Session

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

REFRESH_COOKIE = "rt_refresh"
COOKIE_PATH = "/api/v1/auth"


def _client(request: Request) -> ClientInfo:
    return ClientInfo(ip=client_ip(request), user_agent=request.headers.get("user-agent"))


def respond_with_session(response: Response, session: Session, settings: Settings) -> TokenResponse:
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh_token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )
    return TokenResponse(
        access_token=session.access_token,
        expires_in=settings.access_token_ttl_s,
        must_change_password=session.must_change_password,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={202: {"model": SecondFactorChallengeResponse}},
)
async def login(
    body: LoginRequest, request: Request, response: Response, container: ContainerDep
) -> TokenResponse | JSONResponse:
    """Вход паролем. Со вторым фактором (ДВ-4) и без запомненного устройства — 202 с `challenge`:
    сессии ещё нет, код — `POST /auth/login/second-factor`. Фактор обязателен по разделам доступа
    (ДВ-4б), но не настроен — 202 с `enrollment_required`: настройка — `/auth/login/enroll/*`."""
    result = await container.auth_service.login(
        body.email, body.password, _client(request), body.device_token
    )
    if isinstance(result, SecondFactorRequired | EnrollmentRequired):
        return JSONResponse(
            SecondFactorChallengeResponse(
                challenge=result.challenge,
                enrollment_required=isinstance(result, EnrollmentRequired),
            ).model_dump(),
            status_code=status.HTTP_202_ACCEPTED,
        )
    return respond_with_session(response, result, container.settings)


@router.post("/login/second-factor", response_model=TokenResponse)
async def login_second_factor(
    body: SecondFactorLoginRequest, request: Request, response: Response, container: ContainerDep
) -> TokenResponse:
    """Код приложения-аутентификатора или резервный код (ДВ-4). Неверный — 401
    `second_factor_invalid` (в счёт блокировки), просрочен `challenge` — 401 `auth_failed`."""
    session, device = await container.auth_service.second_factor(
        body.challenge, body.code, body.remember_device, _client(request)
    )
    out = respond_with_session(response, session, container.settings)
    out.device_token = device
    return out


@router.post("/login/enroll/setup", response_model=SecondFactorSetupResponse)
async def login_enroll_setup(
    body: EnrollSetupRequest, request: Request, container: ContainerDep
) -> SecondFactorSetupResponse:
    """Секрет и адрес для QR при входе, когда фактор обязателен, но не настроен (ДВ-4б).
    `challenge` из 202 на `/auth/login` с `enrollment_required`; просрочен — 401 `auth_failed`."""
    setup = await container.auth_service.enroll_setup(body.challenge, body.issuer, _client(request))
    return SecondFactorSetupResponse(secret=setup.secret, otpauth_uri=setup.otpauth_uri)


@router.post("/login/enroll", response_model=TokenResponse)
async def login_enroll(
    body: EnrollRequest, request: Request, response: Response, container: ContainerDep
) -> TokenResponse:
    """Код из приложения включает фактор и открывает сессию; резервные коды — в `backup_codes`,
    один раз. Неверный код — 401 `second_factor_invalid` (в счёт блокировки)."""
    enrolled = await container.auth_service.enroll_complete(
        body.challenge, body.code, _client(request)
    )
    out = respond_with_session(response, enrolled.session, container.settings)
    out.backup_codes = enrolled.backup_codes
    return out


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    container: ContainerDep,
    rt_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    if not rt_refresh:
        raise AuthError("missing refresh cookie")
    session = await container.auth_service.refresh(rt_refresh, _client(request))
    return respond_with_session(response, session, container.settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    container: ContainerDep,
    rt_refresh: Annotated[str | None, Cookie()] = None,
) -> Response:
    if rt_refresh:
        await container.auth_service.logout(rt_refresh)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/change-password", response_model=TokenResponse)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    principal: PrincipalDep,
    container: ContainerDep,
) -> TokenResponse:
    """Смена своего пароля. Прочие сессии закрываются сразу (`password_changed_at`), а эта
    продолжается: в ответе новая пара токенов (access в теле, refresh в cookie, как при входе)."""
    changed = await container.user_service.change_password(
        principal.actor, principal.user_id, body.current_password, body.new_password
    )
    session = await container.auth_service.reissue(principal.user_id, _client(request), changed)
    return respond_with_session(response, session, container.settings)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: ForgotPasswordRequest, container: ContainerDep, background: BackgroundTasks
) -> dict[str, bool]:
    """«Забыли пароль?»: ответ один и тот же для любой учётной записи (перечислять нельзя).

    Ссылка уходит на почту или в Telegram, если у найденного сотрудника есть канал; иначе тихо
    ничего — экран входа заранее говорит «если нет ни того, ни другого, обратитесь к
    администратору». Частоту по адресу и учётной записи ограничивают BFF и сам сервис (3 в час).
    Выпуск и отправка — после ответа (фоновая задача): время ответа не выдаёт, найдена ли учётная
    запись и ушло ли письмо."""
    background.add_task(container.password_reset.request, body.identifier)
    return {"accepted": True}


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password_by_link(body: ResetPasswordRequest, container: ContainerDep) -> Response:
    """Новый пароль по одноразовой ссылке; токен неверный, использованный или просроченный — 422."""
    await container.password_reset.reset(body.token, body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sso/token", response_model=SsoTokenResponse)
async def sso_token(
    principal: PrincipalDep, container: ContainerDep, body: SsoTokenRequest | None = None
) -> SsoTokenResponse:
    """Выдать SSO-токен текущему сотруднику (CONTRACTS §6, sso-token.md).

    Без тела или с `aud = erp` — токен для обмена на сессию ERP; `aud = eds` — для обмена в EDS.
    Обменивает его BFF Платформы.
    """
    token = await container.sso_service.issue_token(
        principal.user_id, aud=body.aud if body else "erp"
    )
    return SsoTokenResponse(token=token)
