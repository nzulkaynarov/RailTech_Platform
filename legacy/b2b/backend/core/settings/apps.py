"""INSTALLED_APPS и Unfold (инженерная админка)."""

from django.utils.translation import gettext_lazy as _

from .base import *  # noqa: F401,F403 — последовательная композиция настроек

# Application definition

INSTALLED_APPS = [
    # Именно `BasicAppConfig`, а НЕ `"unfold"`: дефолтная конфигурация Unfold в своём
    # `ready()` безусловно присваивает `admin.site = UnfoldAdminSite()` и затирает наш
    # инженерный сайт с гейтом входа. Basic-вариант оставляет выбор сайта за
    # `core.admin_config.EngineeringAdminConfig` (ниже по списку).
    "unfold.apps.BasicAppConfig",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "unfold.contrib.inlines",
    "unfold.contrib.import_export",
    "import_export",
    "daphne",
    # Не `django.contrib.admin`, а наша конфигурация: она подменяет сайт админки на
    # инженерный (`core.admin_site.EngineeringAdminSite`) — вход только для суперпользователя
    # или члена группы `system_engineers` (ADR-0001, Phase 5).
    "core.admin_config.EngineeringAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django.contrib.postgres",
    "channels",
    "pgtrigger",
    "pghistory",
    "catalog",
    "crm",
    "sourcing",
    "django_filters",
    "master_data",
    "accounts.apps.AccountsConfig",
    "notifications",
    "core",
    "django_celery_beat",
    "storages",
]

# Unfold Configuration
# ── Импорт/экспорт в админке: под правами модели ──────────────────────────────────────────
# `ImportExportModelAdmin` гейтит только доступ к самой админке, а страницы `/export/` и
# `/import/` — НЕТ. Проверено вживую 20-08: сотрудник-арендатор (is_staff без единого права на
# модель) получал 403 на СПИСКЕ компаний и при этом открывал `/export/` и скачивал CSV со всеми
# 42 компаниями платформы — ИНН, юр. адреса, контакты, банковские счета. Страница `/import/`
# была открыта так же, а `UserResource` до этой волны писал `is_staff` и `role`: загрузка XLSX
# делала кого угодно сотрудником платформы мимо сервисов, аудита и писем.
#
# Коды ниже привязывают обе операции к правам НА МОДЕЛЬ: экспорт требует `view`, импорт —
# `change`. Инженеру с правами всё доступно как прежде; арендатору — 403 на обеих страницах.
IMPORT_EXPORT_EXPORT_PERMISSION_CODE = "view"
IMPORT_EXPORT_IMPORT_PERMISSION_CODE = "change"

UNFOLD = {
    "SITE_TITLE": "RailTech B2B Control Center",
    "SITE_HEADER": "RailTech B2B",
    "SITE_SYMBOL": "train",
    "DASHBOARD_CALLBACK": "core.dashboard.dashboard_callback",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "COLORS": {
        "primary": {
            "50": "239 246 255",
            "100": "219 234 254",
            "200": "191 219 254",
            "300": "147 197 253",
            "400": "96 165 250",
            "500": "59 130 246",
            "600": "37 99 235",
            "700": "29 78 216",
            "800": "30 64 175",
            "900": "30 58 138",
            "950": "23 37 84",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        # True = показывать fallback "All applications" в конце sidebar.
        # Обеспечивает доступ ко всем orphan-моделям (SystemRole, VerificationStatus,
        # KYCDocType и т.п.), которых нет в явной навигации выше. Инженер не
        # должен помнить прямые URL, чтобы добраться до любого лукапа.
        "show_all_applications": True,
        "navigation": [
            {
                "title": _("Каталог"),
                "separator": True,
                "items": [
                    {"title": _("Товары (PIM)"), "icon": "inventory_2", "link": "/admin/catalog/product/"},
                    {"title": _("Офферы поставщиков"), "icon": "local_offer", "link": "/admin/catalog/supplieroffer/"},
                    {"title": _("Категории"), "icon": "folder", "link": "/admin/catalog/category/"},
                    {
                        "title": _("Группы оборудования"),
                        "icon": "precision_manufacturing",
                        "link": "/admin/catalog/equipmentgroup/",
                    },
                ],
            },
            {
                "title": _("Продажи"),
                "separator": True,
                "items": [
                    {"title": _("Сделки"), "icon": "handshake", "link": "/admin/crm/deal/"},
                    {"title": _("Коммерческие предложения"), "icon": "request_quote", "link": "/admin/crm/quote/"},
                    {"title": _("Лиды с сайта"), "icon": "contact_page", "link": "/admin/crm/lead/"},
                    {"title": _("Сообщения"), "icon": "chat", "link": "/admin/crm/message/"},
                ],
            },
            {
                "title": _("Компании и верификация"),
                "separator": True,
                "items": [
                    {"title": _("Все компании"), "icon": "domain", "link": "/admin/accounts/company/"},
                    {
                        "title": _("+ Создать компанию"),
                        "icon": "add_business",
                        "link": "/admin/accounts/company/wizard/",
                    },
                    {
                        "title": _("Заявки на роли"),
                        "icon": "assignment",
                        "link": "/admin/accounts/companyroleapplication/",
                    },
                    {
                        "title": _("Подписки поставщиков"),
                        "icon": "credit_card",
                        "link": "/admin/accounts/suppliersubscription/",
                    },
                    {"title": _("KYC документы"), "icon": "verified_user", "link": "/admin/accounts/kycdocument/"},
                ],
            },
            {
                "title": _("Пользователи"),
                "items": [
                    {"title": _("Все пользователи"), "icon": "group", "link": "/admin/accounts/customuser/"},
                ],
            },
            {
                "title": _("Инженерный доступ"),
                "separator": True,
                "items": [
                    {"title": _("Django Groups"), "icon": "groups", "link": "/admin/auth/group/"},
                    {"title": _("Django Permissions"), "icon": "key", "link": "/admin/auth/permission/"},
                ],
            },
            {
                "title": _("Импорт данных"),
                "separator": True,
                "items": [
                    {"title": _("Задачи импорта"), "icon": "upload_file", "link": "/admin/sourcing/importtask/"},
                    {"title": _("Вложения"), "icon": "attach_file", "link": "/admin/sourcing/attachment/"},
                ],
            },
            {
                "title": _("Справочники: география и логистика"),
                "separator": True,
                "items": [
                    {"title": _("Страны"), "icon": "public", "link": "/admin/master_data/country/"},
                    {"title": _("Валюты"), "icon": "payments", "link": "/admin/master_data/currency/"},
                    {"title": _("Ед. измерения"), "icon": "straighten", "link": "/admin/master_data/unitofmeasure/"},
                    {
                        "title": _("Базис поставки"),
                        "icon": "local_shipping",
                        "link": "/admin/master_data/deliverybasis/",
                    },
                    {
                        "title": _("Ключевые слова Smart Match"),
                        "icon": "label",
                        "link": "/admin/sourcing/domainkeyword/",
                    },
                ],
            },
            {
                "title": _("Справочники: роли и статусы"),
                "separator": True,
                "items": [
                    {
                        "title": _("Системные роли"),
                        "icon": "admin_panel_settings",
                        "link": "/admin/accounts/systemrole/",
                    },
                    {"title": _("Роли в команде"), "icon": "badge", "link": "/admin/accounts/workspacerole/"},
                    {"title": _("Типы компаний"), "icon": "category", "link": "/admin/accounts/companytype/"},
                    {
                        "title": _("Статусы верификации"),
                        "icon": "verified",
                        "link": "/admin/accounts/verificationstatus/",
                    },
                    {"title": _("Типы KYC-документов"), "icon": "description", "link": "/admin/accounts/kycdoctype/"},
                    {"title": _("Этапы сделки"), "icon": "timeline", "link": "/admin/crm/dealstage/"},
                    {"title": _("Статусы КП"), "icon": "flag", "link": "/admin/crm/quotestatus/"},
                    {"title": _("Домены каталога"), "icon": "widgets", "link": "/admin/catalog/domaintype/"},
                    {"title": _("Статусы товара"), "icon": "toggle_on", "link": "/admin/catalog/productstatus/"},
                    {"title": _("Статусы наличия"), "icon": "inventory", "link": "/admin/catalog/stockstatus/"},
                    {
                        "title": _("Типы уведомлений"),
                        "icon": "notifications_active",
                        "link": "/admin/notifications/notificationtype/",
                    },
                ],
            },
            {
                "title": _("Аудит и мониторинг"),
                "separator": True,
                "items": [
                    {"title": _("Уведомления"), "icon": "notifications", "link": "/admin/notifications/notification/"},
                    {"title": _("Журнал email"), "icon": "mail", "link": "/admin/notifications/emaillog/"},
                    {"title": _("Журнал действий"), "icon": "history", "link": "/admin/crm/activitylog/"},
                    {"title": _("История цен КП"), "icon": "fact_check", "link": "/admin/crm/quoteitemhistory/"},
                ],
            },
        ],
    },
}


def _menu_item_permission(link):
    """Пункт меню виден только тому, кто откроет то, куда он ведёт.

    В боковом меню 38 прямых ссылок на страницы Unfold и НИ ОДНОГО ключа `permission`
    (прогон 20-08). Дверь в админку открывает членство в группе `system_engineers`, а
    страницы моделей требуют модельных прав — и группа заводится миграцией БЕЗ единого
    права (`accounts/0006_system_engineers_group`). Инженер видел полное меню, где почти
    каждый пункт вёл на голый 403.

    Это тот же класс, что уже чинили в операторской плоскости, только зеркальный: там пункт
    был спрятан, а дверь открыта; здесь пункт нарисован, а двери нет. Правило одно — меню и
    дверь обязаны говорить одно и то же.

    Право выводим ИЗ ССЫЛКИ, а не перечисляем руками: список из 38 строк, дописанных вручную,
    разъедется с меню на первой же правке.
    """
    parts = [part for part in str(link).strip("/").split("/") if part]
    if len(parts) < 3 or parts[0] != "admin":
        return None
    app_label, model_name = parts[1], parts[2]
    # `/admin/accounts/company/wizard/` — не просмотр, а СОЗДАНИЕ арендатора: тем же правом,
    # которое требует сам мастер (`accounts/wizard.py`), иначе меню опять разойдётся с дверью.
    codename = "add" if parts[3:4] == ["wizard"] else "view"
    required = f"{app_label}.{codename}_{model_name}"

    def _has(request):
        return request.user.has_perm(required)

    return _has


for _group in UNFOLD["SIDEBAR"]["navigation"]:
    for _item in _group.get("items", []):
        _check = _menu_item_permission(_item.get("link", ""))
        if _check is not None:
            _item["permission"] = _check
