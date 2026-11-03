"""Справочник «Типы входящих писем» и правила отправителя (MAIL-TYPES).

Значения — данные администратора; **поведение — код из закрытого списка действий**
(`domain/mail_types.ACTIONS`).
Код типа создаёт сервис из названия и не меняет: письмо хранит его строкой. Использованный тип не
удаляется — его
скрывают (в предложениях помощника и в выборе его нет, у старых писем остаётся). Каждое изменение
— строка
журнала CRM (`dictionary.*`, `mail_rule.*`) в той же транзакции. Права — на уровне API: справочник
и правила
меняет администратор (`integrations:write`).
"""

from collections.abc import Sequence
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, NotFoundError, Reason, ValidationFailedError
from app.domain.mail_types import (
    ACTIONS,
    COLORS,
    ICONS,
    KIND,
    POSITION_STEP,
    ActiveType,
    normalize_pattern,
    slug,
)
from app.models.mail_types import MailSenderRule, MailType
from app.repositories import inbound_mail as mail_repo
from app.repositories import mail_types as repo
from app.repositories import users as users_repo
from app.schemas import mail_types as dto
from app.security import audit
from app.security.principal import Principal

_NAME: Final = ("Типы входящих писем", "Kiruvchi xat turlari", "Incoming mail types")

_ATTRS: Final[tuple[tuple[str, tuple[str, str, str], tuple[str, ...]], ...]] = (
    ("default_action", ("Действие по умолчанию", "Standart harakat", "Default action"), ACTIONS),
    ("color", ("Цвет", "Rang", "Colour"), COLORS),
    ("icon", ("Значок", "Belgi", "Icon"), ICONS),
)
_ACTION_NAMES: Final[dict[str, tuple[str, str, str]]] = {
    "register_incoming": (
        "Зарегистрировать как входящее (ВХ) → директору",
        "Kiruvchi sifatida ro'yxatdan o'tkazish → direktorga",
        "Register as incoming → director",
    ),
    "create_lead": (
        "Создать лид → менеджеру",
        "Lid yaratish → menejerga",
        "Create a lead → manager",
    ),
    "supplier_price": (
        "Загрузить прайс или КП поставщика",
        "Yetkazib beruvchi narxnomasini yuklash",
        "Upload supplier price list or quote",
    ),
    "to_accountant": (
        "Передать бухгалтеру",
        "Buxgalterga topshirish",
        "Hand over to the accountant",
    ),
    "archive_mailing": (
        "В архив как рассылку",
        "Reklama sifatida arxivga",
        "Archive as a newsletter",
    ),
    "reply_template": ("Ответить шаблоном", "Shablon bilan javob berish", "Reply with a template"),
    "suspicious": ("В «Подозрительные» (спам)", "«Shubhali»ga (spam)", "To Suspicious (spam)"),
}
_COLOR_NAMES: Final[dict[str, tuple[str, str, str]]] = {
    "blue": ("Синий", "Ko'k", "Blue"),
    "green": ("Зелёный", "Yashil", "Green"),
    "gold": ("Жёлтый", "Sariq", "Yellow"),
    "red": ("Красный", "Qizil", "Red"),
    "purple": ("Фиолетовый", "Binafsha", "Purple"),
    "cyan": ("Бирюзовый", "Firuza", "Cyan"),
    "default": ("Серый", "Kulrang", "Grey"),
}
_ICON_NAMES: Final[dict[str, tuple[str, str, str]]] = {
    "mail": ("Письмо", "Xat", "Letter"),
    "team": ("Люди", "Odamlar", "People"),
    "calendar": ("Календарь", "Taqvim", "Calendar"),
    "file": ("Документ", "Hujjat", "Document"),
    "wallet": ("Деньги", "Pul", "Money"),
    "bank": ("Учреждение", "Muassasa", "Institution"),
    "notification": ("Рассылка", "Xabarnoma", "Newsletter"),
    "stop": ("Стоп", "To'xtash", "Stop"),
}
_ATTR_NAMES = {"default_action": _ACTION_NAMES, "color": _COLOR_NAMES, "icon": _ICON_NAMES}
_DEFAULTS: Final = {"color": "default", "icon": "mail"}


def _names(values: tuple[str, str, str]) -> dto.LocalizedName:
    return dto.LocalizedName(ru=values[0], uz=values[1], en=values[2])


def catalog() -> dto.DictionaryList:
    attrs = [
        dto.DictionaryAttr(
            key=key,
            type="choice",
            name=_names(name),
            options=[
                dto.DictionaryAttrOption(value=v, name=_names(_ATTR_NAMES[key][v])) for v in options
            ],
        )
        for key, name, options in _ATTRS
    ]
    return dto.DictionaryList(
        items=[dto.Dictionary(kind=KIND, name=_names(_NAME), closed=False, attrs=attrs)]
    )


def present(row: MailType, used: bool | None = None) -> dto.DictionaryItem:
    return dto.DictionaryItem(
        code=row.code,
        name=dto.LocalizedName(ru=row.name_ru, uz=row.name_uz, en=row.name_en),
        attrs={"default_action": row.default_action, "color": row.color, "icon": row.icon},
        active=row.active,
        position=row.position,
        used=used,
    )


def mail_type_out(row: MailType, source: str) -> dto.InboundMailType:
    """Тип у письма: `source` — кто выбрал."""
    return dto.InboundMailType.model_validate(
        {
            "code": row.code,
            "name": {"ru": row.name_ru, "uz": row.name_uz, "en": row.name_en},
            "color": row.color,
            "icon": row.icon,
            "default_action": row.default_action,
            "active": row.active,
            "source": source,
        }
    )


async def active_types(session: AsyncSession) -> list[ActiveType]:
    """Действующие типы для промпта помощника: данные справочника, порядок админа."""
    rows = await repo.all_types(session, include_hidden=False)
    return [ActiveType(r.code, (r.name_ru, r.name_uz, r.name_en)) for r in rows]


def _spec(kind: str) -> None:
    if kind != KIND:
        raise NotFoundError("dictionary not found")


def _clean_attrs(values: dict[str, Any], base: dict[str, str]) -> dict[str, str]:
    options = {key: set(opts) for key, _, opts in _ATTRS}
    bad: dict[str, str] = {}
    for key, value in values.items():
        if key not in options:
            bad[f"attrs.{key}"] = "unknown_attr"
        elif not isinstance(value, str) or value not in options[key]:
            bad[f"attrs.{key}"] = "invalid_value"
    if bad:
        raise ValidationFailedError("invalid attrs", fields=bad)
    merged = {**base, **values}
    if "default_action" not in merged:
        raise ValidationFailedError(
            "default action is required", fields={"attrs.default_action": "required"}
        )
    return {key: merged.get(key) or _DEFAULTS.get(key, "") for key, _, _ in _ATTRS}


async def _free_code(session: AsyncSession, base: str) -> str:
    taken = await repo.taken_codes(session, base)
    if base not in taken:
        return base
    for suffix in "abcdefghijklmnopqrstuvwxyz":
        for second in ("", *"abcdefghijklmnopqrstuvwxyz"):
            code = f"{base}_{suffix}{second}"
            if code not in taken:
                return code
    raise ConflictError("too many similar names", reason=Reason.MAIL_TYPE_NAME_TAKEN)


def _taken() -> ConflictError:
    return ConflictError("name is taken", reason=Reason.MAIL_TYPE_NAME_TAKEN)


class MailTypesService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_items(self, kind: str, *, include_hidden: bool) -> dto.DictionaryItemList:
        _spec(kind)
        async with self._sessions() as session:
            rows = await repo.all_types(session, include_hidden=include_hidden)
            used = await repo.used_codes(session) if include_hidden else None
        return dto.DictionaryItemList(
            items=[present(r, None if used is None else r.code in used) for r in rows]
        )

    async def create(
        self, who: Principal, kind: str, data: dto.DictionaryItemIn
    ) -> dto.DictionaryItem:
        _spec(kind)
        attrs = _clean_attrs(data.attrs, {})
        async with self._sessions() as session, session.begin():
            if await repo.name_taken(session, data.name.ru):
                raise _taken()
            code = await _free_code(session, slug(data.name.en or data.name.ru))
            row = MailType(
                code=code,
                name_ru=data.name.ru,
                name_uz=data.name.uz,
                name_en=data.name.en,
                color=attrs["color"],
                icon=attrs["icon"],
                default_action=attrs["default_action"],
                active=True,
                position=await repo.last_position(session) + POSITION_STEP,
            )
            session.add(row)
            await session.flush()
            await audit.record(
                session, who.actor, "dictionary.created", "mail_type", code, after={"kind": KIND}
            )
            return present(row, used=False)

    async def update(
        self, who: Principal, kind: str, code: str, patch: dto.DictionaryItemPatch
    ) -> dto.DictionaryItem:
        _spec(kind)
        async with self._sessions() as session, session.begin():
            row = await repo.get_type(session, code, for_update=True)
            if row is None:
                raise NotFoundError("value not found")
            action = "dictionary.updated"
            if patch.active is not None and patch.active != row.active:
                row.active = patch.active
                action = "dictionary.shown" if row.active else "dictionary.hidden"
            if patch.name is not None:
                if await repo.name_taken(session, patch.name.ru, except_code=code):
                    raise _taken()
                row.name_ru, row.name_uz, row.name_en = patch.name.ru, patch.name.uz, patch.name.en
            if patch.attrs is not None:
                base = {"default_action": row.default_action, "color": row.color, "icon": row.icon}
                clean = _clean_attrs(patch.attrs, base)
                row.default_action, row.color, row.icon = (
                    clean["default_action"],
                    clean["color"],
                    clean["icon"],
                )
            await session.flush()
            await audit.record(session, who.actor, action, "mail_type", code, after={"kind": KIND})
            return present(row, used=code in await repo.used_codes(session))

    async def delete(self, who: Principal, kind: str, code: str) -> None:
        _spec(kind)
        async with self._sessions() as session, session.begin():
            row = await repo.get_type(session, code, for_update=True)
            if row is None:
                raise NotFoundError("value not found")
            if code in await repo.used_codes(session):
                raise ConflictError("type is in use", reason=Reason.MAIL_TYPE_IN_USE)
            await session.delete(row)
            await session.flush()
            await audit.record(
                session, who.actor, "dictionary.deleted", "mail_type", code, after={"kind": KIND}
            )

    async def reorder(self, who: Principal, kind: str, codes: list[str]) -> dto.DictionaryItemList:
        _spec(kind)
        async with self._sessions() as session, session.begin():
            rows = {r.code: r for r in await repo.all_types(session)}
            if len(codes) != len(set(codes)) or set(codes) != set(rows):
                raise ValidationFailedError("full list required", fields={"codes": "must_list_all"})
            for index, code in enumerate(codes):
                rows[code].position = (index + 1) * POSITION_STEP
            await session.flush()
            await audit.record(
                session, who.actor, "dictionary.reordered", "mail_type", KIND, after={"kind": KIND}
            )
            used = await repo.used_codes(session)
            return dto.DictionaryItemList(items=[present(rows[c], c in used) for c in codes])

    # --- правила отправителя
    # -------------------------------------------------------------------------------

    async def list_rules(self) -> dto.MailSenderRuleList:
        async with self._sessions() as session:
            rows = await repo.rules(session)
            names = await _creators(session, rows)
        return dto.MailSenderRuleList(items=[_rule_out(r, names) for r in rows])

    async def add_rule(self, who: Principal, body: dto.MailSenderRuleIn) -> dto.MailSenderRuleOut:
        """Правило «отправитель или домен → тип»; письмо из карточки получает тип сразу, как и
        открытые «Новые»
        этого отправителя, где тип не выбирал человек."""
        pattern = normalize_pattern(body.pattern)
        if pattern is None:
            raise ValidationFailedError("not an address or a domain", field="pattern")
        async with self._sessions() as session, session.begin():
            kind = await repo.get_type(session, body.type_code)
            if kind is None:
                raise ValidationFailedError("unknown type", field="type_code")
            if not kind.active:
                raise ConflictError("type is hidden", reason=Reason.MAIL_TYPE_INACTIVE)
            if await repo.rule_by_pattern(session, pattern) is not None:
                raise ConflictError("rule exists", reason=Reason.MAIL_RULE_EXISTS)
            rule = MailSenderRule(pattern=pattern, type_code=kind.code, created_by=who.user_id)
            session.add(rule)
            await session.flush()
            applied = await repo.apply_rule_to_open(
                session, pattern, kind.code, except_id=body.mail_id
            )
            if body.mail_id is not None:
                mail = await mail_repo.get(session, body.mail_id, for_update=True)
                if mail is not None and mail.type_source != "manual":
                    mail.type_code, mail.type_source = kind.code, "rule"
                    applied += 1
            await audit.record(
                session,
                who.actor,
                "mail_rule.created",
                "mail_rule",
                rule.id,
                after={"pattern": pattern, "type": kind.code, "applied": applied},
            )
            await session.refresh(rule)
            names = await _creators(session, [rule])
            out = _rule_out(rule, names)
        return dto.MailSenderRuleOut(**out.model_dump(), applied=applied)

    async def delete_rule(self, who: Principal, rule_id: int) -> None:
        async with self._sessions() as session, session.begin():
            rule = await session.get(MailSenderRule, rule_id)
            if rule is None:
                raise NotFoundError("rule not found")
            pattern, code = rule.pattern, rule.type_code
            await session.delete(rule)
            await audit.record(
                session,
                who.actor,
                "mail_rule.deleted",
                "mail_rule",
                rule_id,
                after={"pattern": pattern, "type": code},
            )


async def _creators(session: AsyncSession, rows: Sequence[MailSenderRule]) -> dict[int, str]:
    ids = sorted({r.created_by for r in rows if r.created_by})
    found: dict[int, str] = {}
    for user_id in ids:
        user = await users_repo.get(session, user_id)
        if user is not None:
            found[user_id] = user.full_name
    return found


def _rule_out(rule: MailSenderRule, names: dict[int, str]) -> dto.MailSenderRule:
    return dto.MailSenderRule(
        id=rule.id,
        pattern=rule.pattern,
        type_code=rule.type_code,
        created_at=rule.created_at,
        created_by=names.get(rule.created_by) if rule.created_by else None,
    )
