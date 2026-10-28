"""«Создать заявку» и статус лида для Платформы (CRM-02, CRM-03; SPEC-v3 §3.1 шаг 2, §7.2). Чистые
функции.

* Заявку создают из любой активной стадии лида (не «Отказ») и из клиента; e-mail не обязателен — у
  контакта нужен хотя бы один канал: телефон, e-mail или Telegram.
* `platform_status` — статус лида глазами Платформы (docs/architecture/integration-map.md §3.1):
  вкладки «Лиды» — Новые · В диалоге · Просят КП · Стали клиентами; «Без ответа» и «Отказ» — в
  «Все». Тот же расчёт — SQL в `repositories/crm.py` (фильтр списка); таблица кейсов —
  `tests/unit/domain/test_client_requests.py`.
"""

from enum import StrEnum
from typing import Final

from app.domain.stages import Stage

S = Stage

# Стадии, из которых менеджер создаёт заявку (CRM-03): всё, кроме отказа; `customer` — новая заявка
# клиента.
REQUEST_FROM: Final = frozenset(
    {S.NEW, S.ENGAGED, S.QUALIFIED, S.HANDOFF, S.IN_PROGRESS, S.UNRESPONSIVE, S.WON, S.CUSTOMER}
)
URGENCIES: Final = ("normal", "urgent")
# Причина передачи, по которой лид «просит КП» (триггер `price_or_contract_asked`).
ASKS_PRICE_REASON: Final = "price_or_contract_asked"


class PlatformStatus(StrEnum):
    NEW = "new"
    DIALOG = "dialog"
    WANTS_QUOTE = "wants_quote"
    NO_ANSWER = "no_answer"
    CLIENT = "client"
    LOST = "lost"


def may_create_request(stage: str) -> bool:
    return stage in REQUEST_FROM


def contact_channels(*, phone: str | None, email: str | None, telegram: bool) -> list[str]:
    """Каналы контакта заявки по порядку предпочтения Платформы: Telegram, телефон, e-mail."""
    present = (("telegram", telegram), ("phone", bool(phone)), ("email", bool(email)))
    return [name for name, ok in present if ok]


def platform_status(stage: str, *, asks_price: bool, sla_overdue: bool) -> PlatformStatus:
    """Статус лида для Платформы (CRM-02). `asks_price` — активная передача с причиной
    «цена/условия», `sla_overdue` — открытая передача с истёкшим SLA ответа."""
    if stage == S.LOST:
        return PlatformStatus.LOST
    if stage in (S.CUSTOMER, S.WON):
        return PlatformStatus.CLIENT
    if stage == S.NEW:
        return PlatformStatus.NEW
    if stage in (S.HANDOFF, S.IN_PROGRESS) and asks_price:
        return (
            PlatformStatus.WANTS_QUOTE
        )  # просьба о КП важнее просрочки: главное действие — «Создать заявку»
    if stage == S.UNRESPONSIVE or (stage == S.HANDOFF and sla_overdue):
        return PlatformStatus.NO_ANSWER
    return PlatformStatus.DIALOG
