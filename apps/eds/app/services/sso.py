"""Обмен SSO-токена сотрудника CRM на токен доступа EDS (решение лида L-C1-1).

`jti` фиксируется в своей транзакции ДО поиска сотрудника: отказ 403 токен тоже «сжигает». Сотрудник — только по
`sub` в проекции (`employees`), не по почте; нет — 403 `USER_NOT_PROVISIONED`, неактивен — 403 `USER_INACTIVE`.
Обмен ничего не создаёт и права не меняет.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import status
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.errors import EdsError
from app.models import SsoJti
from app.security.access_token import TTL_SECONDS, issue_access_token
from app.security.sso_token import SsoTokenError, verify_sso_token
from app.services.employees import get_employee

log = structlog.get_logger(__name__)

JTI_KEEP = timedelta(minutes=10)


@dataclass(frozen=True)
class ExchangeResult:
    access_token: str
    expires_in: int = TTL_SECONDS


def invalid_sso_token(reason: str) -> EdsError:
    return EdsError(
        "INVALID_SSO_TOKEN",
        "Токен входа недействителен. Откройте раздел заново.",
        status_code=status.HTTP_401_UNAUTHORIZED,
        details={"reason": reason},
    )


async def consume_jti(session: AsyncSession, jti: str, *, now: datetime) -> bool:
    """Зафиксировать `jti`; `False` — он уже встречался (повтор токена)."""
    stmt = (
        insert(SsoJti)
        .values(jti=jti, expires_at=now + JTI_KEEP)
        .on_conflict_do_nothing(index_elements=[SsoJti.jti])
        .returning(SsoJti.jti)
    )
    return (await session.execute(stmt)).first() is not None


async def purge_expired_jti(session: AsyncSession, *, now: datetime | None = None) -> int:
    result = await session.execute(delete(SsoJti).where(SsoJti.expires_at < (now or datetime.now(UTC))))
    return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult при DELETE


async def exchange(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    token: str,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExchangeResult:
    now = clock()
    try:
        claims = verify_sso_token(token, settings.sso_secrets, now=now.timestamp())
    except SsoTokenError as exc:
        log.warning("sso_exchange_rejected", reason=exc.reason)
        raise invalid_sso_token(exc.reason) from exc

    async with sessions() as session, session.begin():
        fresh = await consume_jti(session, claims.jti, now=now)
    if not fresh:
        log.warning("sso_exchange_rejected", reason="replayed", iss=claims.iss, sub=claims.sub)
        raise invalid_sso_token("replayed")

    async with sessions() as session:
        employee = await get_employee(session, claims.sub)
    if employee is None:
        log.warning("sso_exchange_denied", reason="user_not_provisioned", sub=claims.sub)
        raise EdsError(
            "USER_NOT_PROVISIONED",
            "Вы ещё не подключены к документообороту. Обратитесь к администратору.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    if not employee.is_active:
        log.warning("sso_exchange_denied", reason="user_inactive", sub=claims.sub)
        raise EdsError(
            "USER_INACTIVE",
            "Учётная запись отключена.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    # Аудит обмена (iss, sub, jti); журнал документов — домен, E3.
    log.info("audit", action="sso.exchange", iss=claims.iss, sub=claims.sub, jti=claims.jti)
    return ExchangeResult(
        access_token=issue_access_token(employee.crm_user_id, settings.access_secret.get_secret_value(), now=now)
    )
