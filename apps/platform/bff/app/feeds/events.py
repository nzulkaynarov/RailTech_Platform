"""Лента «Сегодня»: что из журнала ERP показывать и каким текстом.

Журнал ERP (`ActivityLog`) пишет и служебные записи: каждый вход сотрудника через SSO кладёт
`sso.exchange`, отзыв сессий — `sso.revoke`. Для ленты компании это шум, поэтому такие события
отсеиваются (`is_service_event`). Для остальных текст берётся так: код события из таблицы ниже ->
человекочитаемая строка в словаре SPEC-v3 §2; кода в таблице нет, но ERP прислал готовую
человеческую строку (`action`: «Сделка создана») — она; ничего понятного нет — нейтральное
«Действие в ERP». Сырой код в ленте не показывается никогда.

Язык строк пока русский, как у остальных текстов BFF (docs/QUESTIONS.md, Q-PLT-14-5); uz и en —
хвост P2 вместе с переносом формулировок в SPA.
"""

import re

NEUTRAL_TEXT = "Действие в ERP"
ADMIN_TEXT = "Административное действие в ERP"

# Служебные события входа, выхода, SSO и токенов: ни по коду, ни по `action` в ленту не идут.
_SERVICE_PREFIXES = ("sso.", "auth.", "login", "logout", "token.", "session.", "jwt.")
# Машинный код, а не фраза: латиница, цифры, точка, подчёркивание, двоеточие, дефис — без пробелов.
_CODE_LIKE = re.compile(r"^[A-Za-z0-9_.:\-]+$")
# Служебная пометка в начале строки журнала: `[MANUAL_MODE]`, `[FORCE_ADMIN]`.
_MARKER = re.compile(r"^(?:\s*\[[A-Z_]+\])+\s*")

# Таблица `event_code` -> строка ленты. Коды — те, что пишет ERP (`event_code=` в apps/erp/backend).
EVENT_TEXTS: dict[str, str] = {
    "deal.created": "Заявка создана",
    "deal.stage_changed": "Этап заявки изменён",
    "deal.stage_changed_force": "Этап заявки изменён администратором",
    "deal.claimed": "Заявка взята в работу",
    "deal.released": "Заявка возвращена в общую очередь",
    "deal.assigned": "Заявка назначена исполнителю",
    "deal.purchase_actual_set": "Факт закупки внесён",
    "deal.purchase_actual_removed": "Факт закупки удалён",
    "rfq.new": "Новая заявка от клиента",
    "quote.sent": "КП отправлено клиенту",
    "quote.sent_below_floor": "КП отправлено ниже допустимой цены",
    "quote.received": "Получено КП",
    "quote.viewed": "КП просмотрено",
    "quote.viewed_by_client": "Клиент открыл КП",
    "quote.accepted": "КП принято",
    "quote.accepted_by_client": "Клиент одобрил КП",
    "quote.rejected": "КП отклонено",
    "quote.rejected_by_client": "Клиент вернул КП на доработку",
    "quote.expired": "Срок действия КП истёк",
    "quote.duplicated": "КП скопировано",
    "quote.link_revoked": "Ссылка на КП отозвана",
    "quote.item_rematched": "В строке КП заменён товар",
    "quote.fx_fixed": "Курс в КП зафиксирован",
    "quote.fx_overridden": "Курс в КП задан вручную",
    "quote.fx_override_cleared": "Курс в КП сброшен",
    "quote.submitted_for_review": "КП отправлено на согласование",
    "quote.approval_your_turn": "КП ждёт согласования",
    "quote.approval_step_approved": "Шаг согласования КП пройден",
    "quote.approval_step_rejected": "Шаг согласования КП отклонён",
    "quote.approval_returned": "КП возвращено на доработку",
    "quote.approval_complete": "Согласование КП завершено",
    "quote.approval_complete_informed": "Согласование КП завершено",
    "quote.approval_auto": "КП согласовано автоматически",
    "quote.approval_recalled": "Согласование КП отозвано",
    "quote.approved_force": "КП одобрено администратором",
    "contract.created": "Договор создан",
    "contract.signature_required": "Договор ждёт подписи",
    "contract.signed_client": "Договор подписан клиентом",
    "contract.signed_manager": "Договор подписан со стороны компании",
    "contract.signed": "Договор подписан обеими сторонами",
    "contract.cancelled": "Договор отменён",
    "contract.cancelled_force": "Договор отменён администратором",
    "contract.wording_changed": "Формулировка договора изменена",
    "contract.auto_close_failed": "Заявка не закрыта автоматически после подписания",
    "invoice.draft_created": "Счёт создан черновиком",
    "invoice.created": "Счёт создан",
    "invoice.created_manual": "Счёт создан вручную",
    "invoice.issued": "Счёт выставлен",
    "invoice.cancelled": "Счёт отменён",
    "payment.recorded": "Оплата зафиксирована",
    "act.issued": "Акт выставлен",
    "act.signed": "Акт подписан",
    "act.rejected": "Акт отклонён клиентом",
    "act.reissued": "Акт выставлен заново",
    "act.reminded": "Напоминание по акту",
    "act.cancelled": "Акт аннулирован",
    "document.received": "Получен документ",
    "document.downloaded_by_client": "Клиент скачал документ",
    "document.link_issued": "Выдана ссылка на документ",
    "document.link_downloaded": "Документ скачан по ссылке",
    "delivery.line_accepted": "Строка поставки принята клиентом",
    "delivery.line_disputed": "Клиент оспорил строку поставки",
    "delivery.line_event_failed": "Событие поставки не передано",
    "fulfillment.status_changed": "Статус исполнения изменён",
    "fulfillment.accepted_by_client": "Исполнение принято клиентом",
    "fulfillment.accept_failed": "Исполнение не переведено в «принято»",
    "fulfillment.overdue": "Просрочка по исполнению",
    "catalog.category_requested": "Запрошена новая категория",
    "catalog.category_request_reviewed": "Запрос на категорию рассмотрен",
    "catalog.category_request_approved": "Категория заведена",
    "catalog.category_request_rejected": "Запрос на категорию отклонён",
    "product.hs_code_changed": "Код ТН ВЭД изменён",
    "company.linked_by_inn": "Компания связана с клиентом CRM по ИНН",
    "integration.paired_bootstrap": "ERP сопряжена с CRM",
    "integration.paired_code": "ERP сопряжена с CRM по коду",
    "integration.pairing_code_issued": "Выдан код сопряжения",
    "admin.company.own_created": "Создана своя компания",
    "admin.company.archived": "Компания отправлена в архив",
    "admin.company.unarchived": "Компания возвращена в оборот",
    "admin.user.created": "Сотрудник заведён",
    "admin.user.deactivated": "Сотрудник отключён",
    "admin.user.role_changed": "Роли сотрудника изменены",
    "admin.email_template.updated": "Шаблон письма изменён",
    "admin.lookup.updated": "Справочник изменён",
}


def _is_service(value: str) -> bool:
    return value.strip().lower().startswith(_SERVICE_PREFIXES)


def is_service_event(event_code: str, action: str) -> bool:
    """Вход, выход, SSO и токены: служебные записи, в ленте компании их нет."""
    return _is_service(event_code) or _is_service(_MARKER.sub("", action))


def event_text(event_code: str, action: str) -> str:
    """Строка ленты: таблица по коду -> готовая человеческая строка ERP -> нейтральная фраза."""
    code = event_code.strip()
    known = EVENT_TEXTS.get(code)
    if known:
        return known
    human = _MARKER.sub("", action).strip()
    if human and not _CODE_LIKE.fullmatch(human):
        return human
    return ADMIN_TEXT if code.startswith("admin.") else NEUTRAL_TEXT
