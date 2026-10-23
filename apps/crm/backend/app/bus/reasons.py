"""Справочник причин смены стадии лида для события `crm.lead.stage_changed` (решение B4).

В событие уходит только код причины из этого справочника; свободный текст сотрудника («причина
закрытия», заметки), текст ответа модели и прочее остаются в CRM (`stage_transitions.reason`, лента
лида). Всё, чего в справочнике нет, публикуется без `reason`.
"""

from typing import Final

#: Точные причины, которые ставит код CRM, → код.
EXACT: Final[dict[str, str]] = {
    "taken by manager": "taken_by_manager",
    "returned to bot": "returned_to_bot",
    "new deal": "new_deal",
    "repeat deal": "repeat_deal",
    "created manually": "created_manually",
    "linked to client": "linked_to_client",
    "telegram unlinked from client": "telegram_unlinked",
    "lead wrote again": "lead_wrote_again",
    "won": "closed_won",
    "lost": "closed_lost",
}
#: Причины с переменной частью (идентификатор, число дней, действие модели): по префиксу.
PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("qualifier:", "qualifier"),
    ("no reply for ", "no_reply"),
    ("merged with lead", "merged_with_lead"),
)
#: Причина перехода по триггерам эскалации — список кодов триггеров через запятую.
TRIGGER_SOURCE: Final = "trigger"


def reason_code(source: str, reason: str | None) -> str | None:
    """Код причины для события или `None`, если причина — свободный текст."""
    text = (reason or "").strip()
    if text in EXACT:
        return EXACT[text]
    for prefix, code in PREFIXES:
        if text.startswith(prefix):
            return code
    if source == TRIGGER_SOURCE and text:
        return "escalation_trigger"
    return None
