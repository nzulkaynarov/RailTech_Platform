"""Запросы справочника типов писем и правил отправителя (MAIL-TYPES)."""

from collections.abc import Sequence
from typing import Final

from sqlalchemy import ColumnElement, and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.mail_types import best_rule
from app.models.auth import User
from app.models.inbound_mail import InboundMail
from app.models.mail_types import MailSenderRule, MailType
from app.models.platform_roles import PlatformRole, UserPlatformRole

#: Цель передачи → раздел каталога Платформы, дающий право.
PURPOSES: Final = {"payments": "eds.payments", "price": "erp.stock"}


async def all_types(session: AsyncSession, *, include_hidden: bool = True) -> Sequence[MailType]:
    stmt = select(MailType).order_by(MailType.position, MailType.code)
    if not include_hidden:
        stmt = stmt.where(MailType.active.is_(True))
    return (await session.scalars(stmt)).all()


async def type_map(session: AsyncSession) -> dict[str, MailType]:
    return {t.code: t for t in await all_types(session)}


async def get_type(
    session: AsyncSession, code: str, *, for_update: bool = False
) -> MailType | None:
    stmt = select(MailType).where(MailType.code == code)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).first()


async def last_position(session: AsyncSession) -> int:
    return int((await session.execute(select(func.max(MailType.position)))).scalar() or 0)


async def used_codes(session: AsyncSession) -> set[str]:
    """Типы, которые уже у писем или правил: их не удаляют, а скрывают."""
    mails = select(InboundMail.type_code).where(InboundMail.type_code.is_not(None)).distinct()
    rules = select(MailSenderRule.type_code).distinct()
    found = {c for c in (await session.scalars(mails)).all() if c}
    return found | set((await session.scalars(rules)).all())


async def taken_codes(session: AsyncSession, base: str) -> set[str]:
    stmt = select(MailType.code).where(MailType.code.like(f"{base}%"))
    return set((await session.scalars(stmt)).all())


async def name_taken(session: AsyncSession, name: str, *, except_code: str | None = None) -> bool:
    stmt = select(func.count()).where(func.lower(MailType.name_ru) == name.strip().lower())
    if except_code is not None:
        stmt = stmt.where(MailType.code != except_code)
    return bool((await session.execute(stmt)).scalar_one())


async def rules(session: AsyncSession) -> Sequence[MailSenderRule]:
    stmt = select(MailSenderRule).order_by(MailSenderRule.id)
    return (await session.scalars(stmt)).all()


async def rule_by_pattern(session: AsyncSession, pattern: str) -> MailSenderRule | None:
    stmt = select(MailSenderRule).where(MailSenderRule.pattern == pattern)
    return (await session.scalars(stmt)).first()


async def rule_type_for(session: AsyncSession, sender: str) -> str | None:
    """Код типа по правилу отправителя (правило побеждает ИИ); тип отключён — правило молчит."""
    if "@" not in sender:
        return None
    domain = sender.rpartition("@")[2].lower()
    pieces = domain.split(".")
    suffixes = {".".join(pieces[i:]) for i in range(len(pieces))}
    stmt = (
        select(MailSenderRule.pattern, MailSenderRule.type_code)
        .join(MailType, MailType.code == MailSenderRule.type_code)
        .where(
            MailType.active.is_(True),
            or_(MailSenderRule.pattern == sender.lower(), MailSenderRule.pattern.in_(suffixes)),
        )
        .order_by(MailSenderRule.id)
    )
    rows = (await session.execute(stmt)).all()
    return best_rule(sender, [(p, c) for p, c in rows])


def _sender_clause(pattern: str) -> ColumnElement[bool]:
    """Отправитель подходит под шаблон: адрес целиком или домен с поддоменами (граница по точке)."""
    if "@" in pattern:
        return func.lower(InboundMail.from_email) == pattern
    domain = func.split_part(func.lower(InboundMail.from_email), "@", 2)
    return or_(domain == pattern, domain.like(func.concat("%.", pattern)))


async def apply_rule_to_open(
    session: AsyncSession, pattern: str, type_code: str, *, except_id: int | None = None
) -> int:
    """Правило применено к открытым «Новым» письмам этого отправителя без выбора человека.

    Тип ставится только письмам с подтверждённым отправителем; остальным — пометка «правило не
    применено» (в карточке видно, почему)."""
    where = [
        InboundMail.status == "new",
        InboundMail.thread_root_id.is_(None),
        _sender_clause(pattern),
        or_(InboundMail.type_source.is_(None), InboundMail.type_source == "ai"),
    ]
    if except_id is not None:
        where.append(InboundMail.id != except_id)
    stmt = (
        update(InboundMail)
        .where(and_(*where, InboundMail.sender_auth == "verified"))
        .values(type_code=type_code, type_source="rule", rule_skipped=False)
        .returning(InboundMail.id)
    )
    applied = len((await session.execute(stmt)).all())
    await session.execute(
        update(InboundMail)
        .where(and_(*where, InboundMail.sender_auth != "verified"))
        .values(rule_skipped=True)
    )
    return applied


def _grants(purpose: str) -> list[ColumnElement[bool]]:
    """Условия на роль: что нужно роли, чтобы работать с письмом такой цели. Для `price` нужны два
    условия, и они складываются по ВСЕМ ролям человека (одна роль даёт `erp.stock`, другая —
    видимость
    цен поставщиков: у сотрудника с несколькими ролями права объединяются)."""
    base = PlatformRole.access[PURPOSES[purpose]].astext == "full"
    if purpose == "price":
        # `restricted_fields` роли — поля с ограничением, которые она ВИДИТ (platform-rbac.yaml)
        return [base, PlatformRole.restricted_fields.contains(["supplier_prices"])]
    return [base]


async def has_capability(session: AsyncSession, role_ids: Sequence[int], purpose: str) -> bool:
    """Есть ли у человека с этими ролями Платформы право на цель (`payments` | `price`): по
    объединению прав всех его ролей."""
    if not role_ids:
        return False
    for cond in _grants(purpose):
        stmt = (
            select(func.count())
            .select_from(PlatformRole)
            .where(PlatformRole.id.in_(role_ids), cond)
        )
        if not (await session.execute(stmt)).scalar_one():
            return False
    return True


async def handover_targets(
    session: AsyncSession, purpose: str = "payments"
) -> list[tuple[int, str]]:
    """Кому передать письмо: активные сотрудники, чьи роли в сумме дают нужное право (данные, не
    коды).

    `payments` — подтверждать оплату (`eds.payments: full`); `price` — загружать прайсы и видеть
    цены поставщиков (`erp.stock: full` и поле `supplier_prices` у какой-либо из ролей)."""

    def has_role(cond: ColumnElement[bool]) -> ColumnElement[bool]:
        return exists(
            select(1)
            .select_from(UserPlatformRole)
            .join(PlatformRole, PlatformRole.id == UserPlatformRole.role_id)
            .where(UserPlatformRole.user_id == User.id, cond)
        )

    stmt = (
        select(User.id, User.full_name)
        .where(User.is_active.is_(True), *[has_role(c) for c in _grants(purpose)])
        .order_by(User.full_name, User.id)
    )
    return [(int(i), str(n)) for i, n in (await session.execute(stmt)).all()]
