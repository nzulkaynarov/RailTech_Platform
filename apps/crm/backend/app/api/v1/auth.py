"""Аутентификация (SPEC §11): access в теле ответа, refresh — httpOnly cookie с ротацией."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, Request, Response, status

from app.api.deps import ContainerDep, PrincipalDep, client_ip
from app.config import Settings
from app.domain.errors import AuthError
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    SsoExchangeRequest,
    SsoTokenRequest,
    SsoTokenResponse,
    TokenResponse,
)
from app.services.auth import ClientInfo, Session

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


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, request: Request, response: Response, container: ContainerDep
) -> TokenResponse:
    session = await container.auth_service.login(body.email, body.password, _client(request))
    return respond_with_session(response, session, container.settings)


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

    Без тела или с `aud = erp` — переход в ERP; `aud = eds` — токен сотрудника для обмена в EDS
    (у EDS нет внешнего маршрута: `redirect_url` пуст).
    """
    token, redirect_url = await container.sso_service.issue_token(
        principal.user_id, aud=body.aud if body else "erp"
    )
    return SsoTokenResponse(token=token, redirect_url=redirect_url)


@router.post("/sso/exchange", response_model=TokenResponse)
async def sso_exchange(
    body: SsoExchangeRequest, request: Request, response: Response, container: ContainerDep
) -> TokenResponse:
    """Обменять SSO-токен из ERP на сессию CRM (CONTRACTS §6)."""
    session = await container.sso_service.exchange_token(body.token, _client(request))
    return respond_with_session(response, session, container.settings)
