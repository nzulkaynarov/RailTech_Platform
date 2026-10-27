"""Журнал аудита, журнал изменений роли и личные уведомления — схемы `AuditPage`, `RoleJournal`,
`NotificationSettings*` из packages/contracts/openapi/platform-bff.yaml (0.12.0) и перевод записей
аудита и профиля CRM в них.

Записи аудита CRM (`/api/v1/audit`) BFF не интерпретирует: коды действий и объектов остаются
кодами CRM, слова к ним даёт SPA. Единственное, что делает BFF, — вырезает значения секретных
полей (на случай, если какой-то домен записал их в `before`/`after`).
"""

import re
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.rbac_generated import RestrictedField
from app.schemas_admin import AccessLevel

AuditActorType = Literal["user", "system", "bot"]
RoleAction = Literal["create", "update", "delete"]

_ACTOR_TYPES: frozenset[str] = frozenset({"user", "system", "bot"})
_ROLE_ACTIONS: frozenset[str] = frozenset({"create", "update", "delete"})
_LEVELS: frozenset[str] = frozenset({"full", "read"})
_FIELDS: frozenset[str] = frozenset({"cost_margin", "supplier_prices", "totals_only"})
MASK = "***"

# Имя поля нормализуется (регистр, `-`, пробел, `.`, camelCase -> `snake_case`) и режется на слова.
# Секретно поле, в имени которого есть слово: password, passwd, pwd, secret, token, credential(s),
# authorization, pin, key (в том числе `*_key`: api_key, private_key, litellm_api_key); склейки
# `apikey`, `privatekey`, `secretkey`, `accesskey` и множественное число (`keys`, `tokens`) тоже.
# Значение под таким полем маскируется целиком, каким бы оно ни было: строка, число, флаг, список,
# словарь. Пустое значение (`null`, `""`) остаётся: оно говорит «не задано» и ничего не раскрывает.
_WORD = re.compile(r"^(?:password|passwd|pwd|secret|token|credentials?|authorization|pin|key)s?$")
_GLUED = ("apikey", "privatekey", "secretkey", "accesskey")
# Безопасные исключения — явно и только по причине:
# 1) имена-идентификаторы, где «key» значит «код», а не ключ доступа (CRM пишет их в аудит сервисов,
#    продуктов и настроек): `service_key`, `product_key`, `settings_key`, `setting_key`,
#    `section_key`, `agent_context_key`;
# 2) признаки и маски: `*_last4` (последние 4 символа), `*_set`, `*_configured`, `*_present`
#    («задан»), `*_rotated`, `*_missing`, `*_changed` (итог операции над ключами): секрета нет.
_SAFE_NAMES = frozenset(
    {
        "service_key",
        "product_key",
        "settings_key",
        "setting_key",
        "section_key",
        "agent_context_key",
    }
)
_SAFE_SUFFIXES = (
    "_last4",
    "_set",
    "_configured",
    "_present",
    "_rotated",
    "_missing",
    "_changed",
)
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SEPARATORS = re.compile(r"[^a-z0-9]+")


def normalize_key(name: str) -> str:
    """`apiKey`, `API-Key`, `api key` -> `api_key`."""
    return _SEPARATORS.sub("_", _CAMEL.sub("_", name).lower()).strip("_")


def is_secret_key(name: str) -> bool:
    key = normalize_key(name)
    if key in _SAFE_NAMES or key.endswith(_SAFE_SUFFIXES):
        return False
    return any(_WORD.match(part) for part in key.split("_")) or any(g in key for g in _GLUED)


def redact(value: Any) -> Any:
    """Значения секретных полей -> `***` целиком (любой тип); остальное как есть, вглубь тоже."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            hidden = is_secret_key(name) and item is not None and item != ""
            out[name] = MASK if hidden else redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class AuditEntry(BaseModel):
    id: str
    at: datetime
    actor_type: AuditActorType
    actor_id: str | None = None
    actor_name: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    ip: str | None = None


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int = Field(ge=0)
    limit: int
    offset: int


def to_audit_entry(raw: dict[str, Any]) -> AuditEntry:
    """Запись аудита CRM -> запись контракта (секреты вырезаны)."""
    actor_type = str(raw.get("actor_type") or "system")
    actor_id = raw.get("actor_user_id")
    entity_id = raw.get("entity_id")
    before, after = raw.get("before"), raw.get("after")
    return AuditEntry(
        id=str(raw["id"]),
        at=raw["created_at"],
        actor_type=cast(AuditActorType, actor_type if actor_type in _ACTOR_TYPES else "system"),
        actor_id=str(actor_id) if actor_id is not None else None,
        actor_name=str(raw["actor_name"]) if raw.get("actor_name") else None,
        action=str(raw["action"]),
        entity_type=str(raw["entity_type"]),
        entity_id=str(entity_id) if entity_id is not None else None,
        before=redact(before) if isinstance(before, dict) else None,
        after=redact(after) if isinstance(after, dict) else None,
        ip=str(raw["ip"]) if raw.get("ip") else None,
    )


def to_audit_page(raw: dict[str, Any], *, limit: int, offset: int) -> AuditPage:
    return AuditPage(
        items=[to_audit_entry(i) for i in raw.get("items") or [] if isinstance(i, dict)],
        total=int(raw.get("total") or 0),
        limit=limit,
        offset=offset,
    )


class RoleSnapshot(BaseModel):
    name: str
    description: str
    access: dict[str, AccessLevel]
    restricted_fields: list[RestrictedField]


class RoleChange(BaseModel):
    id: str
    at: datetime
    action: RoleAction
    actor_id: str | None = None
    actor_name: str | None = None
    before: RoleSnapshot | None = None
    after: RoleSnapshot | None = None


class RoleJournal(BaseModel):
    items: list[RoleChange]
    total: int = Field(ge=0)


def _snapshot(raw: Any) -> RoleSnapshot | None:
    """Снимок роли из `before`/`after` аудита CRM; неизвестные уровни и поля отбрасываются."""
    if not isinstance(raw, dict):
        return None
    access = raw.get("access")
    fields = raw.get("restricted_fields")
    return RoleSnapshot(
        name=str(raw.get("name") or ""),
        description=str(raw.get("description") or ""),
        access={
            str(k): cast(AccessLevel, v)
            for k, v in (access if isinstance(access, dict) else {}).items()
            if v in _LEVELS
        },
        restricted_fields=[
            cast(RestrictedField, f)
            for f in (fields if isinstance(fields, list) else [])
            if f in _FIELDS
        ],
    )


def to_role_journal(raw: dict[str, Any]) -> RoleJournal:
    """Записи аудита `platform_role.*` -> журнал изменений роли (чужие действия пропускаются)."""
    items: list[RoleChange] = []
    for row in raw.get("items") or []:
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or "").rsplit(".", 1)[-1]
        if action not in _ROLE_ACTIONS:
            continue
        actor_id = row.get("actor_user_id")
        items.append(
            RoleChange(
                id=str(row["id"]),
                at=row["created_at"],
                action=cast(RoleAction, action),
                actor_id=str(actor_id) if actor_id is not None else None,
                actor_name=str(row["actor_name"]) if row.get("actor_name") else None,
                before=_snapshot(row.get("before")),
                after=_snapshot(row.get("after")),
            )
        )
    return RoleJournal(items=items, total=int(raw.get("total") or 0))


# --- личные уведомления (профиль) ---------------------------------------------------------------


class NotificationSettings(BaseModel):
    telegram_linked: bool
    notify_leads: bool
    notify_system: bool
    delivery_failed_at: datetime | None = None


class NotificationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notify_leads: StrictBool | None = None
    notify_system: StrictBool | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "NotificationSettingsUpdate":
        if not self.model_fields_set:
            raise ValueError("укажите notify_leads или notify_system")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} не может быть null")
        return self


def to_notification_settings(me: dict[str, Any]) -> NotificationSettings:
    """Профиль CRM (`/me`) -> личные уведомления. Идентификатор Telegram наружу не отдаётся."""
    failed = me.get("tg_dm_failed_at")
    return NotificationSettings(
        telegram_linked=me.get("tg_user_id") is not None,
        notify_leads=bool(me.get("notify_leads", True)),
        notify_system=bool(me.get("notify_system", True)),
        delivery_failed_at=failed if isinstance(failed, str) and failed else None,
    )
