"""Что делать с учётной записью в ERP при изменении пользователя CRM (FIX-11, M3-CRM-06).

Чистые функции: решение «провижининг», «отзыв сессий» или «ничего» по состоянию до и после.
Доступом к ERP управляет CRM (ADR-0003): выдача (`"erp"` в `platform_access`) → провижининг,
снятие или деактивация пользователя → отзыв сессий; роли или имя у пользователя с доступом
изменились → повторный провижининг (права ERP следуют за ролью CRM, `domain/erp_permissions.py`).
Выбор системных ролей ERP (`erp_role_codes`, FIX-63) — тоже повод для повторного провижининга.
"""

from dataclasses import dataclass
from typing import Literal

SyncAction = Literal["provision", "revoke"]
ERP = "erp"


@dataclass(frozen=True, slots=True)
class AccessState:
    """Срез пользователя, от которого зависит его учётная запись в ERP."""

    platform_access: tuple[str, ...]
    is_active: bool
    roles: tuple[str, ...]
    full_name: str
    # Системные роли ERP, выбранные админом (FIX-63): порядок не важен, как и у `roles`.
    erp_role_codes: tuple[str, ...] = ()

    @property
    def has_erp(self) -> bool:
        return ERP in self.platform_access


def sync_action(before: AccessState, after: AccessState) -> SyncAction | None:
    """Действие над ERP после изменения; `None` — ERP ничего знать не нужно."""
    if before.has_erp and (not after.has_erp or (before.is_active and not after.is_active)):
        return "revoke"
    if not (after.has_erp and after.is_active):
        return None
    became_available = not before.has_erp or not before.is_active
    profile_changed = (set(before.roles), before.full_name, set(before.erp_role_codes)) != (
        set(after.roles),
        after.full_name,
        set(after.erp_role_codes),
    )
    return "provision" if became_available or profile_changed else None


def access_audit_action(before: AccessState, after: AccessState) -> str | None:
    """Аудит выдачи и снятия доступа: `platform_access.granted` | `platform_access.revoked`."""
    if after.has_erp and not before.has_erp:
        return "platform_access.granted"
    if before.has_erp and not after.has_erp:
        return "platform_access.revoked"
    return None
