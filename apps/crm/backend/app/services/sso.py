"""Выпуск SSO-токена сотрудника для ERP и EDS (CONTRACTS §6, docs/architecture/sso-token.md).

Токен (iss=crm, aud=erp|eds, sub=crm_user_id) обменивает BFF Платформы на сессию ERP или токен EDS.
Обратного обмена (токен ERP -> сессия CRM) нет: он служил переходу из старого ERP в старую CRM.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import Literal

import jwt
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import snapshots
from app.config import Settings
from app.domain.erp_permissions import erp_access
from app.domain.erp_sync import ERP
from app.domain.errors import ConflictError, ForbiddenError, Reason
from app.models.auth import User
from app.repositories import platform_roles as platform_roles_repo
from app.repositories import users as repo
from app.services.auth import AuthService

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

    async def issue_token(self, user_id: int, aud: Literal["erp", "eds"] = "erp") -> str:
        """Выпустить JWT SSO-токен сотрудника: `erp` — для обмена на сессию ERP, `eds` — на токен
        EDS (sso-token.md, «Токен сотрудника для EDS»)."""
        if not self._settings.platform_sso_enabled:
            raise ForbiddenError("platform sso is disabled")
        async with self._sessions() as session:
            user = await session.get(User, user_id)
            if aud == "eds":
                # Только активному сотруднику с правами EDS из его ролей по каталогу (ADR-0012
                # п. 5); иначе один отказ `eds_access_denied` (sso-token.md).
                held = (
                    []
                    if user is None
                    else await platform_roles_repo.roles_of_user(session, user.id)
                )
                eds_permissions = snapshots.eds_permissions(
                    held, is_active=user is not None and bool(user.is_active)
                )
                if user is None or not eds_permissions:
                    raise ForbiddenError("no permissions in eds", reason=Reason.EDS_ACCESS_DENIED)
                return self._encode(user, aud, {"permissions": eds_permissions})
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
        claims = {"role": _primary_role(roles), "permissions": list(access.permissions)}
        return self._encode(user, aud, claims)

    def _encode(self, user: User, aud: str, claims: Mapping[str, object]) -> str:
        """JWT HS256 первым значением `PLATFORM_SSO_SECRET`; срок жизни — 60 с, `jti` — UUID v4."""
        secrets = self._settings.platform_sso_secrets
        if not secrets:
            raise ConflictError(
                "platform sso secret is not configured", reason=Reason.SSO_NOT_CONFIGURED
            )
        now = int(time.time())
        payload = {
            "iss": "crm",
            "aud": aud,
            "sub": str(user.id),
            "email": user.email,
            "name": user.full_name,
            **claims,
            "iat": now,
            "exp": now + SSO_TOKEN_TTL_S,
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(payload, secrets[0], algorithm=SSO_ALGORITHM)


def _primary_role(roles: list[str]) -> str:
    """Старшая роль CRM для claim `role` (admin > manager > viewer); без ролей — viewer."""
    for role in ("admin", "manager"):
        if role in roles:
            return role
    return "viewer"
