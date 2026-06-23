"""Single source of truth for accounts lookup CODES.

These mirror the `code` of seeded lookup rows (WorkspaceRole, SystemRole,
CompanyType, VerificationStatus). Reference these constants in business logic
instead of bare string literals — a typo becomes an AttributeError, not a silent
runtime miss. The rows themselves still live in the DB (names, i18n, sort_order);
this is just the stable contract between code and data.

NB: do NOT import this from migrations — migrations must stay frozen.
"""

from django.db import models


class WorkspaceRoleCode(models.TextChoices):
    OWNER = "OWNER", "Владелец"
    SALES_MANAGER = "SALES_MANAGER", "Менеджер по продажам"
    DIRECTOR = "DIRECTOR", "Директор"
    FOREIGN_TRADE_SPECIALIST = "FOREIGN_TRADE_SPECIALIST", "Менеджер ВЭД"
    LOGIST = "LOGIST", "Логист"
    CONTRACT_MANAGER = "CONTRACT_MANAGER", "Договорник"
    PROCUREMENT_MANAGER = "PROCUREMENT_MANAGER", "Менеджер закупок"
    BUYER_MANAGER = "BUYER_MANAGER", "Менеджер покупателя"
    MEMBER = "MEMBER", "Участник"


class SystemRoleCode(models.TextChoices):
    ADMIN = "ADMIN", "Администратор платформы"
    USER = "USER", "Пользователь"


class CompanyTypeCode(models.TextChoices):
    CLIENT = "CLIENT", "Клиент (покупатель)"
    SUPPLIER = "SUPPLIER", "Поставщик (продавец)"
    # DEPRECATED participant roles (retired 2026-06-23). Marketplace sides are now
    # SELLER (SUPPLIER) + BUYER (CLIENT). "Производитель" is ONLY an OEM brand
    # reference (catalog.Manufacturer), not a company role. Kept for migration/history;
    # deactivated as selectable types and remapped to SUPPLIER by accounts migration 0018.
    MANUFACTURER = "MANUFACTURER", "Производитель (DEPRECATED — см. catalog.Manufacturer)"
    PLANT = "PLANT", "Завод (DEPRECATED)"


# Company types whose members operate on the seller side. A manufacturer that sells
# is simply a SUPPLIER; the OEM-as-brand lives in catalog.Manufacturer.
SELLER_COMPANY_TYPES = (CompanyTypeCode.SUPPLIER,)


class VerificationStatusCode(models.TextChoices):
    L1_UNVERIFIED = "L1_UNVERIFIED", "Не верифицирован"
    PROFILE_SUBMITTED = "PROFILE_SUBMITTED", "Профиль подан"
    L2_VERIFIED = "L2_VERIFIED", "Верифицирован (L2)"
    L3_CONTRACTED = "L3_CONTRACTED", "Контракт (L3)"
