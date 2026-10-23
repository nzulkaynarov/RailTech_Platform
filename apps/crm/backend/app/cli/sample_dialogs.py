"""`python -m app sample-dialogs` — выгрузка случайных диалогов для разметки (PLAN Фаза 7).

Еженедельно 20 диалогов за 7 дней → YAML (stdout) с замаскированными PII и пустыми
полями разметки. Менеджеры заполняют `label`; кейсы с `golden: true` переносятся
в `evals/golden/` (формат — docs/systems/crm/evals-labeling.md, скилл `eval-case`).
"""

import argparse
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import get_container
from app.models.leads import Conversation, Lead, Message
from app.models.qualification import Escalation
from app.security.pii import mask_text

LABEL_TEMPLATE = {
    "handoff": "",  # ok | unnecessary (зря передал) | missed (надо было передать)
    "tone": "",  # ok | bad
    "facts": "",  # ok | wrong | invented
    "comment": "",
    "golden": False,  # true — сделать golden-кейс
}


def to_item(
    lead: Lead, messages: list[Message], reasons: list[str], crm_base_url: str
) -> dict[str, Any]:
    """Диалог лида в формате разметки; тексты — через маскирование PII."""
    dialog = []
    for m in messages:
        turn: dict[str, Any] = {"role": m.role, "text": mask_text(m.text)}
        if m.role == "bot" and m.meta.get("action"):
            turn["action"] = m.meta["action"]
        dialog.append(turn)
    return {
        "lead_id": lead.id,
        "crm_url": f"{crm_base_url.rstrip('/')}/leads/{lead.id}",
        "language": lead.language,
        "stage": lead.stage,
        "escalation_reasons": sorted(set(reasons)),
        "dialog": dialog,
        "label": dict(LABEL_TEMPLATE),
    }


async def sample(
    session: AsyncSession, since: datetime, count: int, rng: random.Random, crm_base_url: str
) -> list[dict[str, Any]]:
    lead_ids = sorted(
        (
            await session.scalars(
                select(Conversation.lead_id)
                .join(Message, Message.conversation_id == Conversation.id)
                .where(Message.role == "bot", Message.created_at >= since)
                .distinct()
            )
        ).all()
    )
    chosen = sorted(rng.sample(lead_ids, min(count, len(lead_ids))))
    if not chosen:
        return []
    leads = {
        lead.id: lead
        for lead in (await session.scalars(select(Lead).where(Lead.id.in_(chosen)))).all()
    }
    rows = (
        await session.execute(
            select(Conversation.lead_id, Message)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Conversation.lead_id.in_(chosen))
            .order_by(Message.id)
        )
    ).all()
    messages: dict[int, list[Message]] = defaultdict(list)
    for lead_id, message in rows:
        messages[lead_id].append(message)
    reasons: dict[int, list[str]] = defaultdict(list)
    for e in (
        await session.scalars(select(Escalation).where(Escalation.lead_id.in_(chosen)))
    ).all():
        reasons[e.lead_id] += e.reason_codes
    return [
        to_item(leads[i], messages[i], reasons[i], crm_base_url)
        for i in chosen
        if leads[i].erased_at is None
    ]


async def run(args: argparse.Namespace) -> int:
    container = get_container()
    cfg = await container.settings_service.get()
    since = datetime.now(UTC) - timedelta(days=args.days)
    async with container.session_factory() as session:
        rng = random.Random(args.seed)  # noqa: S311 — выборка для разметки, не криптография
        items = await sample(session, since, args.count, rng, cfg.company.crm_base_url)
    await container.engine.dispose()
    header = (
        f"# Разметка диалогов: {len(items)} шт. с {since:%Y-%m-%d}; "
        "формат — docs/systems/crm/evals-labeling.md\n"
    )
    sys.stdout.write(header + yaml.safe_dump(items, allow_unicode=True, sort_keys=False))
    return 0
