"""
Enterprise lookup seed — idempotent data migration.

Source of truth for business codes used across services.py / FSM / permissions.
Runs once per environment. On a fresh DB, after `migrate`, every code referenced
by the codebase MUST exist here.

Rule 1 (CLAUDE.md): business lookups = data migrations, not management commands.

Reverse: no-op. We never roll back seeded lookup rows — that would cascade-delete
production Deals / Quotes / Companies. If a code must be removed, do it via a new
migration that renames/retires it with a data fixup.
"""
from django.db import migrations


# ─────────────────────────── lookup definitions ───────────────────────────

DEAL_STAGES = [
    ('DRAFT',           'Черновик',                 10),
    ('KYC_PENDING',     'Ожидание KYC',             20),
    ('RFQ_OPEN',        'Открытый RFQ',             25),
    ('SOURCING',        'Подбор поставщиков',       30),
    ('CALCULATING',     'Расчёт цен',               40),
    ('QUOTE_SENT',      'КП отправлено',            50),
    ('CONTRACT_SIGNED', 'Договор подписан',         60),
    ('CLOSED_WON',      'Закрыта (выиграна)',       70),
    ('CLOSED_LOST',     'Закрыта (проиграна)',      80),
]

QUOTE_STATUSES = [
    ('DRAFT',    'Черновик',         10),
    ('SENT',     'Отправлено',       20),
    ('APPROVED', 'Одобрено',         30),
    ('REJECTED', 'Отклонено',        40),
    ('EXPIRED',  'Срок истёк',       50),
]

COMPANY_TYPES = [
    ('CLIENT',              'Клиент',          10),
    ('SUPPLIER',            'Поставщик',       20),
    ('MANUFACTURER',        'Производитель',   30),
    ('LOGISTICS_PROVIDER',  'Логистика',       40),
]

VERIFICATION_STATUSES = [
    ('L1_UNVERIFIED',     'Не верифицирован',  10),
    ('PROFILE_SUBMITTED', 'Профиль на проверке', 20),
    ('L2_VERIFIED',       'KYC подтверждён',   30),
    ('L3_CONTRACTED',     'Договор заключён',  40),
    ('REJECTED',          'Отклонён',          50),
]

# SystemRole: (code, name, sort_order, is_staff_level)
SYSTEM_ROLES = [
    ('GUEST',           'Гость',              10, False),
    ('CLIENT',          'Клиент',             20, False),
    ('EMPLOYEE',        'Сотрудник',          30, False),
    ('ACCOUNT_MANAGER', 'Аккаунт-менеджер',   40, True),
    ('SALES_MANAGER',   'Менеджер продаж',    50, True),
    ('ADMIN',           'Администратор',      60, True),
]

WORKSPACE_ROLES = [
    ('OWNER',                'Владелец',           10),
    ('ACCOUNTANT',           'Бухгалтер',          20),
    ('PROCUREMENT_MANAGER',  'Менеджер закупок',   30),
    ('MEMBER',               'Сотрудник',          40),
]

KYC_DOC_TYPES = [
    ('CHARTER',   'Устав',                       10),
    ('LICENSE',   'Лицензия',                    20),
    ('PASSPORT',  'Паспорт директора',           30),
    ('TAX_CERT',  'Свидетельство о налоговом учёте', 40),
    ('BANK_REF',  'Банковская справка',          50),
    ('OTHER',     'Другое',                      60),
]

PRODUCT_STATUSES = [
    ('DRAFT',     'Черновик',   10),
    ('PUBLISHED', 'Опубликован', 20),
    ('ARCHIVED',  'Архивирован', 30),
]

STOCK_STATUSES = [
    ('IN_STOCK', 'В наличии',   10),
    ('EXPECTED', 'Ожидается',   20),
    ('ON_ORDER', 'Под заказ',   30),
]

# DomainType: (code, name, sku_prefix, sort_order)
DOMAIN_TYPES = [
    ('GENERAL',            'Общие товары',         'GEN', 10),
    ('RAILWAY_MACHINERY',  'Железнодорожная техника', 'RW',  20),
    ('SERVICES',           'Услуги',               'SRV', 30),
]

NOTIFICATION_TYPES = [
    ('INFO',    'Информация',     10),
    ('SUCCESS', 'Успех',          20),
    ('WARNING', 'Предупреждение', 30),
    ('ERROR',   'Ошибка',         40),
]


# ─────────────────────────── seed functions ───────────────────────────

def _seed_simple(model, rows):
    """(code, name, sort_order)"""
    for code, name, sort_order in rows:
        model.objects.get_or_create(
            code=code,
            defaults={'name': name, 'sort_order': sort_order, 'is_active': True},
        )


def seed_all(apps, schema_editor):
    DealStage = apps.get_model('crm', 'DealStage')
    QuoteStatus = apps.get_model('crm', 'QuoteStatus')
    CompanyType = apps.get_model('accounts', 'CompanyType')
    VerificationStatus = apps.get_model('accounts', 'VerificationStatus')
    SystemRole = apps.get_model('accounts', 'SystemRole')
    WorkspaceRole = apps.get_model('accounts', 'WorkspaceRole')
    KYCDocType = apps.get_model('accounts', 'KYCDocType')
    ProductStatus = apps.get_model('catalog', 'ProductStatus')
    StockStatus = apps.get_model('catalog', 'StockStatus')
    DomainType = apps.get_model('catalog', 'DomainType')
    NotificationType = apps.get_model('notifications', 'NotificationType')

    _seed_simple(DealStage,          DEAL_STAGES)
    _seed_simple(QuoteStatus,        QUOTE_STATUSES)
    _seed_simple(CompanyType,        COMPANY_TYPES)
    _seed_simple(VerificationStatus, VERIFICATION_STATUSES)
    _seed_simple(WorkspaceRole,      WORKSPACE_ROLES)
    _seed_simple(KYCDocType,         KYC_DOC_TYPES)
    _seed_simple(ProductStatus,      PRODUCT_STATUSES)
    _seed_simple(StockStatus,        STOCK_STATUSES)
    _seed_simple(NotificationType,   NOTIFICATION_TYPES)

    # SystemRole has is_staff_level flag
    for code, name, sort_order, is_staff_level in SYSTEM_ROLES:
        SystemRole.objects.get_or_create(
            code=code,
            defaults={
                'name': name, 'sort_order': sort_order,
                'is_active': True, 'is_staff_level': is_staff_level,
            },
        )

    # DomainType has sku_prefix
    for code, name, sku_prefix, sort_order in DOMAIN_TYPES:
        DomainType.objects.get_or_create(
            code=code,
            defaults={
                'name': name, 'sku_prefix': sku_prefix,
                'sort_order': sort_order, 'is_active': True,
            },
        )


# ─────────────────────────── historical backfill ───────────────────────────

def backfill_existing(apps, schema_editor):
    """Heal rows that were created before the Phase 2-5 models/fields existed."""
    from django.utils import timezone
    from datetime import timedelta

    Company = apps.get_model('accounts', 'Company')
    CompanyType = apps.get_model('accounts', 'CompanyType')
    CustomUser = apps.get_model('accounts', 'CustomUser')
    SystemRole = apps.get_model('accounts', 'SystemRole')
    SupplierSubscription = apps.get_model('accounts', 'SupplierSubscription')
    Deal = apps.get_model('crm', 'Deal')
    DealStage = apps.get_model('crm', 'DealStage')

    # Companies without any type → CLIENT (historical default).
    client_type = CompanyType.objects.filter(code='CLIENT').first()
    if client_type:
        for c in Company.objects.all():
            if not c.types.exists():
                c.types.add(client_type)

    # Users without role → GUEST.
    guest_role = SystemRole.objects.filter(code='GUEST').first()
    if guest_role:
        CustomUser.objects.filter(role__isnull=True).update(role=guest_role)

    # Subscriptions without valid_until (malformed legacy data) → 30-day trial.
    today = timezone.now().date()
    for sub in SupplierSubscription.objects.filter(valid_until__isnull=True, status='TRIAL'):
        sub.valid_until = today + timedelta(days=30)
        sub.next_payment_date = sub.valid_until
        sub.save(update_fields=['valid_until', 'next_payment_date'])

    # Deals without stage → DRAFT.
    draft = DealStage.objects.filter(code='DRAFT').first()
    if draft:
        Deal.objects.filter(stage__isnull=True).update(stage=draft)


def noop(apps, schema_editor):
    # Reverse is a no-op: we never auto-delete lookup rows (FK chains in prod).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        ('accounts', '0008_company_has_iso9001_company_is_verified_and_more'),
        ('catalog', '0005_alter_category_domain_type_alter_category_icon_and_more'),
        ('crm', '0009_beat_schedule'),
        ('notifications', '0003_alter_notification_created_at_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_all, reverse_code=noop),
        migrations.RunPython(backfill_existing, reverse_code=noop),
    ]
