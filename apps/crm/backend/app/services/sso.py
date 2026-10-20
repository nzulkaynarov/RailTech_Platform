"""Сервис платформенного SSO CRM ↔ ERP (CONTRACTS §6, packages/contracts/sso-token.md, M3-CRM-06).

Реализует:
1. Выпуск SSO-токена в ERP (iss=crm, aud=erp, sub=crm_user_id).
2. Проверку и обмен SSO-токена из ERP (iss=erp, aud=crm) на сессию CRM с защитой от replay-атак.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import structlog
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.erp_permissions import erp_access
from app.domain.erp_sync import ERP
from app.domain.errors import AuthError, ConflictError, ForbiddenError, Reason
from app.models.auth import SsoReplayToken, User
from app.repositories import users as repo
from app.security import audit
from app.security.audit import Actor
from app.security.tokens import new_family
from app.services.auth import AuthService, ClientInfo, Session

logger = structlog.get_logger(__name__)

SSO_ALGORITHM = "HS256"
SSO_TOKEN_TTL_S = 60
SSO_CLOCK_LEEWAY_S = 5


class SsoService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: Settings,
        auth_service: AuthService,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._auth_service = auth_service

    async def issue_token(self, user_id: int) -> tuple[str, str]:
        """Выпустить JWT SSO-токен для перехода текущего сотрудника в ERP."""
        if not self._settings.platform_sso_enabled:
            raise ForbiddenError("platform sso is disabled")
        async with self._sessions() as session:
            user = await session.get(User, user_id)
            if user is None or not user.is_active:
                raise ForbiddenError("user inactive", reason=Reason.USER_INACTIVE)
            # Переход в ERP — только тем, кому админ выдал доступ (FIX-11, S-5); истина здесь,
            # а не в скрытой кнопке шапки.
            if ERP not in (user.platform_access or []):
                raise ForbiddenError(
                    "platform access to erp is not granted", reason=Reason.PLATFORM_ACCESS_DENIED
                )
            roles = await repo.roles_of(session, user.id)

        # Права — по карте «роль CRM → каталог ERP» (S-11): ни одного кода вне каталога ERP.
        access = erp_access(roles)
        primary_role = _primary_role(roles)
        permissions = list(access.permissions)

        now = int(time.time())
        jti = str(uuid.uuid4())

        payload = {
            "iss": "crm",
            "aud": "erp",
            "sub": str(user.id),
            "email": user.email,
            "name": user.full_name,
            "role": primary_role,
            "permissions": permissions,
            "iat": now,
            "exp": now + SSO_TOKEN_TTL_S,
            "jti": jti,
        }

        secrets = self._settings.platform_sso_secrets
        if not secrets:
            raise ConflictError(
                "platform sso secret is not configured", reason=Reason.SSO_NOT_CONFIGURED
            )
        token = jwt.encode(payload, secrets[0], algorithm=SSO_ALGORITHM)

        erp_base = self._settings.erp_frontend_url.rstrip("/")
        redirect_url = f"{erp_base}/sso/exchange"

        return token, redirect_url

    async def exchange_token(self, token: str, client: ClientInfo) -> Session:
        """Проверить SSO-токен от ERP и обменять его на сессию CRM."""
        if not self._settings.platform_sso_enabled:
            raise ForbiddenError("platform sso is disabled")
        if not token or not isinstance(token, str):
            raise AuthError("token required")

        secrets = self._settings.platform_sso_secrets
        payload = None
        last_err: Exception | None = None

        for secret in secrets:
            try:
                payload = jwt.decode(
                    token,
                    secret,
                    algorithms=[SSO_ALGORITHM],
                    audience="crm",
                    issuer="erp",
                    leeway=SSO_CLOCK_LEEWAY_S,
                    options={"require": ["exp", "iat", "sub", "iss", "aud", "jti"]},
                )
            except (
                jwt.ExpiredSignatureError,
                jwt.InvalidAudienceError,
                jwt.InvalidIssuerError,
            ) as exc:
                last_err = exc
                break
            except jwt.PyJWTError as exc:
                last_err = exc
                continue

        if payload is None:
            logger.warning("sso_verification_failed", error=str(last_err))
            raise AuthError("invalid sso token")

        # Срок жизни: exp − iat ≤ 60 с (+ допуск часов), иначе отказ даже при верной подписи (S-7).
        try:
            lifetime = int(payload["exp"]) - int(payload["iat"])
        except (ValueError, TypeError):
            raise AuthError("invalid sso token") from None
        if lifetime <= 0 or lifetime > SSO_TOKEN_TTL_S + SSO_CLOCK_LEEWAY_S:
            logger.warning("sso_lifetime_exceeded", lifetime=lifetime)
            raise AuthError("invalid sso token")

        jti = payload.get("jti")
        if not jti or not isinstance(jti, str):
            raise AuthError("invalid jti")

        now_dt = datetime.now(UTC)

        async with self._sessions() as session, session.begin():
            # Очистка устаревших jti старше 15 минут
            await session.execute(
                delete(SsoReplayToken).where(
                    SsoReplayToken.created_at < now_dt - timedelta(minutes=15)
                )
            )

            # Одноразовость jti держит сама БД: параллельный повтор ждёт первую вставку и
            # пустой ответ ON CONFLICT DO NOTHING — тот же отказ, а не IntegrityError и 500.
            claimed = await session.execute(
                insert(SsoReplayToken)
                .values(jti=jti)
                .on_conflict_do_nothing(index_elements=[SsoReplayToken.jti])
                .returning(SsoReplayToken.jti)
            )
            if claimed.scalar_one_or_none() is None:
                logger.warning("sso_replay_detected", jti=jti)
                raise AuthError("token already used")

            # Пользователь — только по sub (id в CRM); по e-mail не ищем (sso-token.md, S-3).
            user: User | None = None
            with contextlib.suppress(ValueError, TypeError):
                user = await session.get(User, int(payload["sub"]))

            if user is None:
                raise ForbiddenError("user not provisioned", reason=Reason.USER_NOT_PROVISIONED)
            if not user.is_active:
                raise ForbiddenError("user inactive", reason=Reason.USER_INACTIVE)

            name = str(payload.get("name") or "").strip()
            if name and user.full_name != name:
                user.full_name = name

            await audit.record(
                session,
                Actor(user.id, ip=client.ip),
                "sso.exchange",
                "user",
                user.id,
                after={
                    "iss": payload.get("iss"),
                    "sub": payload.get("sub"),
                    "jti": jti,
                    "ip": client.ip or "",
                },
            )

            session_data = await self._auth_service._issue(
                session, user, new_family(), client, now_dt
            )

        return session_data


def _primary_role(roles: list[str]) -> str:
    """Старшая роль CRM для claim `role` (admin > manager > viewer); без ролей — viewer."""
    for role in ("admin", "manager"):
        if role in roles:
            return role
    return "viewer"
