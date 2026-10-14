from django.db import models
from django.utils.translation import gettext_lazy as _

from master_data.models import AbstractLookup

# ────────────────────────────────────────────
# Справочники модуля Accounts
# ────────────────────────────────────────────


class SystemRole(AbstractLookup):
    """
    Системная роль пользователя на уровне платформы.

    Seed: ADMIN (Platform Admin), USER (обычный пользователь компании).
    Больше ролей нет — права внутри компаний регулирует WorkspaceRole.
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Системная роль")
        verbose_name_plural = _("Справочник: Системные роли")


class CompanyType(AbstractLookup):
    """
    Тип/роль компании на платформе.
    Seed: CLIENT, MANUFACTURER, SUPPLIER, LOGISTICS_PROVIDER
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Тип компании")
        verbose_name_plural = _("Справочник: Типы компаний")


class WorkspaceRole(AbstractLookup):
    """
    Роль пользователя внутри компании.

    Роли типа-специфичные. Пример seed:
      BUYER  → OWNER, PROCUREMENT_MANAGER, MANAGER
      SELLER → OWNER, SALES_MANAGER, LOGIST
      MANUFACTURER → OWNER, CONTRACT_MANAGER, FOREIGN_TRADE_SPECIALIST

    applicable_to_types ограничивает, в каких компаниях роль можно назначить.
    Пустой набор = роль универсальная (например, OWNER).
    """

    applicable_to_types = models.ManyToManyField(
        "accounts.CompanyType",
        blank=True,
        related_name="workspace_roles",
        verbose_name=_("Применимо к типам компаний"),
        help_text=_(
            "Если пусто — роль универсальна. Если указаны типы — роль " "доступна только в компаниях этих типов."
        ),
    )

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Роль в компании")
        verbose_name_plural = _("Справочник: Роли в компании")
