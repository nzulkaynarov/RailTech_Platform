"""Снимки сущностей CRM для событий шины (event-carried state transfer, CONTRACTS §9, L11).

Подписчик заменяет свою проекцию снимком целиком, поэтому снимок полный и в канонической форме:
телефоны — E.164, почта — нижний регистр, длины — по схеме. Издатель шины проверяет `data` строго
(`additionalProperties: false`), и один неудачный старый телефон в карточке не должен ронять
изменение клиента: значение, которое не приводится к виду схемы, не публикуется (`None` у
необязательных полей, обрезка у строк), а в лог пишется предупреждение без самого значения.

`updated_at` берётся из базы после `flush`: его ведёт триггер `set_updated_at`, и значение в объекте
после UPDATE устарело (в async-сессии обращение к просроченному атрибуту — `MissingGreenlet`).
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bot_menu import normalize_phone
from app.domain.platform_roles import RoleGrant, eds_permissions_of
from app.domain.platform_roles_generated import ROLE_ACCESS, SYSTEM_ROLE_CODES
from app.models.auth import User
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity
from app.models.platform_roles import PlatformRole
from app.repositories import platform_roles as platform_roles_repo
from app.security.audit import Actor

logger = structlog.get_logger(__name__)

_PHONE: Final = re.compile(r"^\+[1-9][0-9]{6,14}$")
_EMAIL: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ROLE_CODE: Final = re.compile(r"^[A-Z][A-Z0-9_]*$")
_LANGUAGES: Final = frozenset({"ru", "uz", "en"})
_LEAD_STAGES: Final = frozenset(
    {
        "new",
        "engaged",
        "qualified",
        "handoff",
        "in_progress",
        "won",
        "customer",
        "lost",
        "unresponsive",
    }
)
_LEAD_SOURCES: Final = frozenset({"telegram", "web", "phone", "email", "referral", "sandbox"})
_TEMPLATE_PREFIX: Final = "tpl:"


def clip(value: str | None, limit: int) -> str | None:
    """Строка без краёв, не длиннее схемы; пусто — `None`."""
    text = (value or "").strip()
    return text[:limit] or None


def required_text(value: str | None, limit: int, *, fallback: str = "—") -> str:
    """Обязательная строка схемы (`minLength: 1`): пустое имя не роняет публикацию."""
    return clip(value, limit) or fallback


def clean_phone(value: str | None) -> str | None:
    """Телефон в E.164 по схеме; не приводится — `None`."""
    raw = (value or "").strip()
    if not raw:
        return None
    phone = raw if _PHONE.fullmatch(raw) else normalize_phone(raw)
    if phone is None or not _PHONE.fullmatch(phone):
        logger.warning("bus_snapshot_phone_dropped", length=len(raw))
        return None
    return phone


def clean_email(value: str | None) -> str | None:
    """Почта в нижнем регистре; не похожа на адрес или длиннее схемы — `None`."""
    email = (value or "").strip().lower()
    if not email:
        return None
    if len(email) > 255 or not _EMAIL.fullmatch(email):
        logger.warning("bus_snapshot_email_dropped", length=len(email))
        return None
    return email


def utc(moment: datetime) -> str:
    """Момент в RFC 3339 UTC (поле `date-time` схемы)."""
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def actor_of(actor: Actor) -> dict[str, Any]:
    """Кто изменил: сотрудник, бот или система (`Actor` схем CRM и identity)."""
    if actor.type == "user" and actor.user_id is not None:
        return {"type": "staff", "crm_user_id": actor.user_id}
    return {"type": "bot" if actor.type == "bot" else "system"}


async def fresh_updated_at(session: AsyncSession, model: Any, row_id: int) -> datetime:
    """`updated_at` строки в базе после `flush` (триггер ведёт его при каждом UPDATE)."""
    await session.flush()
    value = await session.scalar(select(model.updated_at).where(model.id == row_id))
    return value if value is not None else datetime.now(UTC)


async def db_now(session: AsyncSession) -> datetime:
    """Начало транзакции по часам базы: то же время, что триггер пишет в `updated_at`."""
    value = await session.scalar(select(func.now()))
    return value if value is not None else datetime.now(UTC)


async def user_ref(session: AsyncSession, user_id: int | None) -> dict[str, Any] | None:
    """Сотрудник-ответственный (`UserRef`); нет или удалён — `None`."""
    if user_id is None:
        return None
    name = await session.scalar(select(User.full_name).where(User.id == user_id))
    if name is None:
        return None
    return {"crm_user_id": user_id, "full_name": required_text(name, 255)}


async def client_snapshot(session: AsyncSession, client: Client) -> dict[str, Any]:
    return {
        "crm_client_id": client.id,
        "erp_company_id": client.erp_company_id,
        "name": required_text(client.name, 255),
        "inn": clip(client.inn, 32),
        "segment": clip(client.segment, 64),
        "is_active": bool(client.is_active),
        "owner": await user_ref(session, client.owner_user_id),
        "updated_at": utc(await fresh_updated_at(session, Client, client.id)),
    }


async def _telegram_user_id(session: AsyncSession, identity_id: int | None) -> int | None:
    if identity_id is None:
        return None
    return await session.scalar(
        select(TelegramIdentity.tg_user_id).where(TelegramIdentity.id == identity_id)
    )


async def contact_snapshot(session: AsyncSession, contact: ClientContact) -> dict[str, Any]:
    erp_company_id = await session.scalar(
        select(Client.erp_company_id).where(Client.id == contact.client_id)
    )
    return {
        "crm_contact_id": contact.id,
        "crm_client_id": contact.client_id,
        "erp_company_id": erp_company_id,
        "full_name": required_text(contact.full_name, 255),
        "position": clip(contact.position, 255),
        "phone_e164": clean_phone(contact.phone_e164),
        "email": clean_email(contact.email),
        "telegram_user_id": await _telegram_user_id(session, contact.telegram_identity_id),
        "is_primary": bool(contact.is_primary),
        "updated_at": utc(await fresh_updated_at(session, ClientContact, contact.id)),
    }


async def lead_snapshot(session: AsyncSession, lead: Lead) -> dict[str, Any]:
    """Лид без контактов и переписки: персональные данные лида в события не попадают."""
    return {
        "crm_lead_id": lead.id,
        "crm_client_id": lead.client_id,
        "display_name": (lead.display_name or "").strip()[:255],
        "company_name": clip(lead.company_name, 255),
        "stage": lead.stage if lead.stage in _LEAD_STAGES else "new",
        "source": lead.source if lead.source in _LEAD_SOURCES else "telegram",
        "language": lead.language if lead.language in _LANGUAGES else "ru",
        "score": min(100, max(0, int(lead.score or 0))),
        "assigned_user": await user_ref(session, lead.assigned_user_id),
        "erp_request_id": lead.erp_request_id,
        "updated_at": utc(await fresh_updated_at(session, Lead, lead.id)),
    }


def role_code(role: PlatformRole) -> str | None:
    """Код роли Платформы для события (`ADMIN`, `MANAGER`, …); у ролей без кода — `None`."""
    code = (role.code or "").removeprefix(_TEMPLATE_PREFIX)
    return code if _ROLE_CODE.fullmatch(code) else None


def eds_permissions(roles: Sequence[PlatformRole], *, is_active: bool) -> list[str]:
    """Права EDS сотрудника из его ролей по каталогу (сортированный список); неактивный — пусто.

    Матрица системной роли — из каталога (она неизменна, ADR-0012 п. 2), прочих — данные роли."""
    grants = [
        RoleGrant(dict(ROLE_ACCESS[r.code]), (), r.code)
        if r.is_system and r.code in SYSTEM_ROLE_CODES
        else RoleGrant(dict(r.access), tuple(r.restricted_fields), r.code)
        for r in roles
    ]
    return list(eds_permissions_of(grants, is_active=is_active))


def user_fields(user: User, roles: Sequence[PlatformRole]) -> dict[str, Any]:
    """Поля снимка сотрудника, зависящие от его данных и ролей (всё, кроме id и `updated_at`).

    По двум таким срезам — до и после — считается `changed_fields` (`changed_user_fields`)."""
    codes = sorted({code for role in roles if (code := role_code(role))})
    access = sorted(set(user.platform_access or ["crm"]) & {"crm", "erp"})
    is_active = bool(user.is_active)
    return {
        "email": (user.email or "").strip().lower(),
        "full_name": required_text(user.full_name, 255),
        "position": clip(user.position, 120),
        "language": user.language if user.language in _LANGUAGES else "ru",
        "is_active": is_active,
        "platform_roles": codes,
        "systems": access,
        "erp_role_codes": sorted(set(user.erp_role_codes or [])),
        "permissions": {"eds": eds_permissions(roles, is_active=is_active)},
    }


def changed_user_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Имена полей снимка, изменившихся между двумя срезами `user_fields`."""
    return sorted(name for name in after if before.get(name) != after[name])


async def user_snapshot(session: AsyncSession, user: User) -> dict[str, Any]:
    """Сотрудник без пароля, токенов, Telegram и журнала входов (идентичность v1 живёт в CRM).

    `permissions.eds` — права EDS из ролей (ADR-0012 п. 5, sso-token.md): подписчик заменяет их
    целиком; пустой список — доступа к EDS нет.
    """
    roles = await platform_roles_repo.roles_of_user(session, user.id)
    return {
        "crm_user_id": user.id,
        **user_fields(user, roles),
        "updated_at": utc(await fresh_updated_at(session, User, user.id)),
    }
