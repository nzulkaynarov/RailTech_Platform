"""Записка передачи для выдачи `GET /inbox` (CRM-06, D1-1).

То же содержание, что у карточки лида в канале команды (`channel_card`, SPEC §9.1): запрос, факты
квалификации, причина, рекомендуемый шаг и последнее сообщение лида — но данными, а не текстом:
подписи кодов (причины, срок, роль) делает экран на языке сотрудника. Продукты — названиями из
справочника (неизвестный ключ и служебный `company` не показываются, как в канале).
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leads import Lead
from app.models.qualification import Escalation
from app.repositories import crm
from app.schemas.leads import HandoffFacts, HandoffNote
from app.services.channel_card import LAST_MAX, products

FACT_KEYS: Final = ("timeline", "decision_role", "budget_hint", "company", "company_size", "region")


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def note(
    lead: Lead,
    escalation: Escalation | None,
    product_names: Mapping[str, str],
    last_text: str | None,
) -> HandoffNote:
    stored: dict[str, Any] = dict(lead.qualification or {})
    facts = HandoffFacts(
        interest=products(list(lead.product_interest or []), product_names),
        **{key: _text(stored.get(key)) for key in FACT_KEYS},
    )
    last = last_text.strip().replace("\n", " ")[:LAST_MAX] if last_text else None
    return HandoffNote(
        request=_text(lead.need_summary),
        facts=facts,
        reason_codes=list(escalation.reason_codes or []) if escalation else [],
        reason_text=escalation.reason_text if escalation else None,
        recommendation=escalation.recommendation if escalation else None,
        last_lead_message=last or None,
    )


async def notes(
    session: AsyncSession, leads: Sequence[Lead], escalations: Mapping[int, Escalation]
) -> dict[int, HandoffNote]:
    """Записки для лидов очереди: два запроса на всех (продукты, последние сообщения)."""
    keys = sorted({key for lead in leads for key in (lead.product_interest or [])})
    names = await crm.product_names(session, keys)
    last = await crm.last_lead_texts(session, [lead.id for lead in leads])
    return {
        lead.id: note(lead, escalations.get(lead.id), names, last.get(lead.id)) for lead in leads
    }
