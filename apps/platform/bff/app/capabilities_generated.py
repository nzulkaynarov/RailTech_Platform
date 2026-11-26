"""Действия делегирования (СОТР-2). ГЕНЕРИРУЕТСЯ — не править руками.

Источник: packages/contracts/platform-rbac-capabilities.yaml.
Пересоздание: `make -C apps/platform rbac`. Логика — `app/delegation.py`.
"""

from typing import Any, Final

# Области списка «Что делегировано»
AREAS: Final[dict[str, dict[str, str]]] = {
    "sales": {
        "ru": "Продажи",
        "uz": "Sotuvlar",
        "en": "Sales",
    },
    "documents": {
        "ru": "Документы",
        "uz": "Hujjatlar",
        "en": "Documents",
    },
    "money": {
        "ru": "Деньги",
        "uz": "Pul",
        "en": "Money",
    },
    "purchasing": {
        "ru": "Закупки и склад",
        "uz": "Xaridlar va ombor",
        "en": "Purchasing and stock",
    },
    "work": {
        "ru": "Работа",
        "uz": "Iş",
        "en": "Work",
    },
    "admin": {
        "ru": "Администрирование",
        "uz": "Administratsiya",
        "en": "Administration",
    },
}

# Действие: код, область, подпись ru/uz/en и разделы каталога с уровнем
CAPABILITIES: Final[tuple[dict[str, Any], ...]] = (
    {
        "code": "leads.work",
        "area": "sales",
        "label": {
            "ru": "Вести лиды и клиентов",
            "uz": "Lidlar va mijozlar bilan işlaş",
            "en": "Work leads and clients",
        },
        "grants": {
            "crm.leads": "full",
            "crm.clients": "full",
            "chats.external": "full",
        },
    },
    {
        "code": "leads.triage",
        "area": "sales",
        "label": {
            "ru": "Разбирать лиды и передавать менеджеру",
            "uz": "Lidlarni saralab, menejerga topşiriş",
            "en": "Triage leads and hand them to a manager",
        },
        "grants": {
            "crm.leads": "read",
            "crm.leads.triage": "full",
        },
    },
    {
        "code": "leads.view",
        "area": "sales",
        "label": {
            "ru": "Смотреть воронку и переписку с клиентами",
            "uz": "Voronka va mijozlar yozişmasini köriş",
            "en": "View the funnel and client conversations",
        },
        "grants": {
            "crm.leads": "read",
            "chats.external": "read",
        },
    },
    {
        "code": "quote.prepare",
        "area": "sales",
        "label": {
            "ru": "Готовить расчёт и КП",
            "uz": "Hisob-kitob va TT tayyorlaş",
            "en": "Prepare calculations and quotes",
        },
        "grants": {
            "erp.calc": "full",
        },
    },
    {
        "code": "quote.approve",
        "area": "sales",
        "label": {
            "ru": "Утверждать и отправлять КП",
            "uz": "TT ni tasdiqlaş va yuboriş",
            "en": "Approve and send quotes",
        },
        "grants": {
            "eds.drafts": "full",
        },
    },
    {
        "code": "calc.goods",
        "area": "sales",
        "label": {
            "ru": "Визировать расчёт: товары и склад",
            "uz": "Hisobni vizalaş: tovar va ombor",
            "en": "Sign off calculations: goods and stock",
        },
        "grants": {
            "erp.calc.goods": "full",
        },
    },
    {
        "code": "calc.services",
        "area": "sales",
        "label": {
            "ru": "Визировать расчёт: услуги",
            "uz": "Hisobni vizalaş: xizmatlar",
            "en": "Sign off calculations: services",
        },
        "grants": {
            "erp.calc.services": "full",
        },
    },
    {
        "code": "inbox.register",
        "area": "documents",
        "label": {
            "ru": "Регистрировать письма",
            "uz": "Xatlarni röyxatga oliş",
            "en": "Register letters",
        },
        "grants": {
            "eds.inbox.register": "full",
        },
    },
    {
        "code": "inbox.resolve",
        "area": "documents",
        "label": {
            "ru": "Накладывать резолюции",
            "uz": "Rezolyutsiya qöyiş",
            "en": "Put resolutions",
        },
        "grants": {
            "eds.inbox": "full",
        },
    },
    {
        "code": "mail.view",
        "area": "documents",
        "label": {
            "ru": "Видеть всю очередь почты",
            "uz": "Poçtaning butun navbatini köriş",
            "en": "See the whole mail queue",
        },
        "grants": {
            "crm.mail": "read",
        },
    },
    {
        "code": "projects.work",
        "area": "documents",
        "label": {
            "ru": "Вести договоры и проекты",
            "uz": "Şartnoma va loyihalarni yuritiş",
            "en": "Handle contracts and projects",
        },
        "grants": {
            "eds.projects": "full",
        },
    },
    {
        "code": "projects.view",
        "area": "documents",
        "label": {
            "ru": "Смотреть договоры и проекты",
            "uz": "Şartnoma va loyihalarni köriş",
            "en": "View contracts and projects",
        },
        "grants": {
            "eds.inbox": "read",
            "eds.drafts": "read",
            "eds.projects": "read",
        },
    },
    {
        "code": "memo.create",
        "area": "documents",
        "label": {
            "ru": "Создавать внутренние документы",
            "uz": "Içki hujjatlarni yaratiş",
            "en": "Create internal documents",
        },
        "grants": {
            "eds.memo.create": "full",
        },
    },
    {
        "code": "memo.approve",
        "area": "documents",
        "label": {
            "ru": "Согласовывать внутренние документы",
            "uz": "Içki hujjatlarni kelişiş",
            "en": "Approve internal documents",
        },
        "grants": {
            "eds.memo.approve": "full",
        },
    },
    {
        "code": "visa.legal",
        "area": "documents",
        "label": {
            "ru": "Визировать договоры как юрист",
            "uz": "Şartnomalarni yurist sifatida vizalaş",
            "en": "Sign off contracts as legal",
        },
        "grants": {
            "eds.visa.legal": "full",
        },
    },
    {
        "code": "visa.finance",
        "area": "documents",
        "label": {
            "ru": "Визировать счета, акты и договоры как бухгалтер",
            "uz": "Hisob, dalolatnoma va şartnomalarni buxgalter sifatida vizalaş",
            "en": "Sign off invoices, acts and contracts as accountant",
        },
        "grants": {
            "eds.visa.finance": "full",
        },
    },
    {
        "code": "signing.manage",
        "area": "documents",
        "label": {
            "ru": "Выдавать права подписи",
            "uz": "Imzo huquqlarini beriş",
            "en": "Grant signing authority",
        },
        "grants": {
            "eds.signing.manage": "full",
        },
    },
    {
        "code": "payments.confirm",
        "area": "money",
        "label": {
            "ru": "Подтверждать оплату",
            "uz": "Tölovni tasdiqlaş",
            "en": "Confirm payments",
        },
        "grants": {
            "eds.payments": "full",
        },
    },
    {
        "code": "payments.view",
        "area": "money",
        "label": {
            "ru": "Смотреть оплаты",
            "uz": "Tölovlarni köriş",
            "en": "View payments",
        },
        "grants": {
            "eds.payments": "read",
        },
    },
    {
        "code": "stock.work",
        "area": "purchasing",
        "label": {
            "ru": "Вести каталог и закупки",
            "uz": "Katalog va xaridlarni yuritiş",
            "en": "Handle catalog and purchasing",
        },
        "grants": {
            "erp.stock": "full",
        },
    },
    {
        "code": "stock.view",
        "area": "purchasing",
        "label": {
            "ru": "Смотреть каталог и склад",
            "uz": "Katalog va omborni köriş",
            "en": "View catalog and stock",
        },
        "grants": {
            "erp.stock": "read",
        },
    },
    {
        "code": "summary.view",
        "area": "work",
        "label": {
            "ru": "Видеть сводку по компании",
            "uz": "Kompaniya xulosasini köriş",
            "en": "See the company summary",
        },
        "grants": {
            "dashboard.summary": "full",
        },
    },
    {
        "code": "chats.internal",
        "area": "work",
        "label": {
            "ru": "Писать коллегам и вести свои задачи",
            "uz": "Hamkasblarga yoziş va öz vazifalarini yuritiş",
            "en": "Message colleagues and keep own tasks",
        },
        "grants": {
            "dashboard.queue": "full",
            "chats.internal": "full",
        },
    },
    {
        "code": "admin.staff",
        "area": "admin",
        "label": {
            "ru": "Управлять сотрудниками и делегированием",
            "uz": "Xodimlar va vakolatlarni boşqariş",
            "en": "Manage employees and delegation",
        },
        "grants": {
            "admin": "full",
        },
    },
    {
        "code": "admin.view",
        "area": "admin",
        "label": {
            "ru": "Смотреть настройки и журнал",
            "uz": "Sozlamalar va jurnalni köriş",
            "en": "View settings and the log",
        },
        "grants": {
            "admin": "read",
        },
    },
    {
        "code": "admin.system",
        "area": "admin",
        "label": {
            "ru": "Менять каналы, подключения и ИИ",
            "uz": "Kanallar, ulanişlar va AI ni özgartiriş",
            "en": "Change channels, connections and AI",
        },
        "grants": {
            "admin.system": "full",
        },
    },
    {
        "code": "company.settings",
        "area": "admin",
        "label": {
            "ru": "Менять настройки компании и шаблоны",
            "uz": "Kompaniya sozlamalari va şablonlarni özgartiriş",
            "en": "Change company settings and templates",
        },
        "grants": {
            "company.settings": "full",
        },
    },
)
