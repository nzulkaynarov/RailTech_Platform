"""Сервис платформенного SSO CRM ↔ ERP (CONTRACTS §6, packages/contracts/sso-token.md, M3-CRM-06).

Реализует:
1. Выпуск SSO-токена в ERP (iss=crm, aud=erp, sub=crm_user_id).
2. Проверку и обмен SSO-токена из ERP (iss=erp, aud=crm) на сессию CRM с защитой от replay-атак.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import AuthError, ForbiddenError
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

DEFAULT_ADMIN_PERMISSIONS = [
    "quote.view",
    "quote.edit",
    "quote.view_cost_margin",
    "quote.build",
    "deal.manage",
    "catalog.manage",
    "supply.manage",
    "contract.manage",
    "finance.manage",
]

DEFAULT_MANAGER_PERMISSIONS = [
    "quote.view",
    "quote.edit",
    "quote.view_cost_margin",
    "quote.build",
    "deal.manage",
]


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
                raise ForbiddenError("user inactive")

            roles = await repo.roles_of(session, user.id)

        primary_role = "viewer"
        permissions: list[str] = ["quote.view"]
        if "admin" in roles:
            primary_role = "admin"
            permissions = list(DEFAULT_ADMIN_PERMISSIONS)
        elif "manager" in roles:
            primary_role = "manager"
            permissions = list(DEFAULT_MANAGER_PERMISSIONS)

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
        primary_secret = secrets[0] if secrets else "dev-platform-sso-secret"
        token = jwt.encode(payload, primary_secret, algorithm=SSO_ALGORITHM)

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

            # Проверка одноразовости jti (10 минут)
            existing_replay = await session.get(SsoReplayToken, jti)
            if existing_replay is not None:
                logger.warning("sso_replay_detected", jti=jti)
                raise AuthError("token already used")

            session.add(SsoReplayToken(jti=jti))
            await session.flush()

            # Поиск пользователя по sub (crm_user_id) или email
            user: User | None = None
            try:
                sub_id = int(payload["sub"])
                user = await session.get(User, sub_id)
            except (ValueError, TypeError):
                pass

            if user is None and payload.get("email"):
                user = await session.scalar(
                    select(User).where(User.email == str(payload["email"]).strip().lower())
                )

            if user is None or not user.is_active:
                raise ForbiddenError("user inactive")

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
