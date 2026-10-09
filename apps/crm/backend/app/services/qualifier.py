"""Прогон квалификатора по лиду (SPEC §7.2): модель → постобработка в коде → журнал.

Вызов модели — вне транзакции; применение — под блокировкой строки лида с
пересчётом решения на свежем состоянии. Итог каждого прогона — строка
`qualifier_runs` (в том числе при ошибке модели).
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.qualifier.graph import QualifierAgent, QualifierInput, QualifierResult
from app.domain import qualifier_decision as qd
from app.domain.keywords import find_terms
from app.domain.qualification import LeadSignals, Qualification
from app.domain.stages import Stage, TransitionSource
from app.models.leads import Lead, Message
from app.models.qualification import QualifierRun
from app.repositories import kb as kb_repo
from app.repositories import leads as repo
from app.schemas.settings import AppSettings, Language
from app.services import escalation, stages
from app.services.lead_messenger import LeadMessenger
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

EscalationHook = Callable[[int, int], Awaitable[None]]
QUALIFICATION_FIELDS = frozenset(Qualification.model_fields)


class QualifierService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        agent: QualifierAgent,
        messenger: LeadMessenger,
        on_escalation: EscalationHook | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._agent = agent
        self._messenger = messenger
        self._on_escalation = on_escalation

    async def run(self, lead_id: int) -> int | None:
        """Id записи `qualifier_runs` или None, если лида квалифицировать нельзя."""
        cfg = await self._settings.get()
        async with self._sessions() as session:
            prepared = await self._prepare(session, lead_id, cfg)
        if prepared is None:
            return None
        data, trigger_id, new_lead_texts = prepared
        try:
            result: QualifierResult | None = await self._agent.run(data)
            error = None
        except Exception as exc:
            logger.exception("qualifier_failed", lead_id=lead_id)
            result, error = None, f"{type(exc).__name__}: {str(exc)[:300]}"
        run_id, notice, escalation_id = await self._apply(
            lead_id, cfg, result, error, trigger_id, new_lead_texts
        )
        if notice is not None:
            await self._messenger.send(lead_id, notice, {"notice": "escalation"})
        if escalation_id is not None and self._on_escalation is not None:
            await self._on_escalation(lead_id, escalation_id)
        return run_id

    async def _prepare(
        self, session: AsyncSession, lead_id: int, cfg: AppSettings
    ) -> tuple[QualifierInput, int | None, list[str]] | None:
        lead = await repo.get_lead(session, lead_id)
        if lead is None or lead.erased_at is not None or lead.consent_given_at is None:
            return None
        messages = await repo.recent_messages(session, lead_id, cfg.bot.history_messages)
        previous = await _last_trigger_id(session, lead_id)
        lead_messages = [m for m in messages if m.role == "lead"]
        new_texts = [m.text for m in lead_messages if previous is None or m.id > previous]
        products = await kb_repo.list_products(session)
        data = QualifierInput(
            lead_id=lead.id,
            company=cfg.company.name,
            products=[(p.key, p.name) for p in products],
            card=_card(lead),
            transcript=[(m.role, m.text) for m in messages if m.role != "system"],
        )
        trigger_id = lead_messages[-1].id if lead_messages else None
        return data, trigger_id, new_texts

    async def _apply(
        self,
        lead_id: int,
        cfg: AppSettings,
        result: QualifierResult | None,
        error: str | None,
        trigger_id: int | None,
        new_lead_texts: list[str],
    ) -> tuple[int | None, str | None, int | None]:
        async with self._sessions() as session, session.begin():
            lead = await repo.get_lead(session, lead_id, for_update=True)
            if lead is None:
                return None, None, None
            run = QualifierRun(
                lead_id=lead_id,
                trigger_message_id=trigger_id,
                score_before=lead.score,
                score_after=lead.score,
                error=error,
            )
            notice: str | None = None
            escalation_id: int | None = None
            if result is not None:
                facts = await self._facts(session, lead, cfg, new_lead_texts)
                decision = qd.decide(
                    _state(lead),
                    result.output,
                    facts,
                    cfg.escalation.triggers(),
                    cfg.qualification.criteria(),
                )
                await _apply_decision(session, lead, decision, result)
                applied = await escalation.apply(
                    session,
                    lead,
                    decision.hits,
                    cfg,
                    datetime.now(UTC),
                    reason_text=result.output.escalation_reason,
                    recommendation=result.output.next_best_action or None,
                )
                _fill_run(run, lead, decision, result, applied is not None)
                if applied is not None:
                    escalation_id = applied.escalation_id
                    if applied.plan.lead_text is not None:
                        notice = cfg.lead_notice(applied.plan.lead_text, _lang(lead))
            session.add(run)
            await session.flush()
            logger.info(
                "qualifier_applied",
                lead_id=lead_id,
                run_id=run.id,
                stage=lead.stage,
                score=lead.score,
                triggers=run.triggers_fired,
            )
            return run.id, notice, escalation_id

    async def _facts(
        self, session: AsyncSession, lead: Lead, cfg: AppSettings, new_lead_texts: list[str]
    ) -> qd.TurnFacts:
        products = await kb_repo.list_products(session)
        text = "\n".join(new_lead_texts)
        return qd.TurnFacts(
            price_quoted=await _last_price_quoted(session, lead.id),
            competitor_mentioned=bool(find_terms(text, cfg.competitors.terms)),
            known_products={p.key for p in products},
        )


async def _apply_decision(
    session: AsyncSession, lead: Lead, decision: qd.QualifierDecision, result: QualifierResult
) -> None:
    for target in decision.stage_path:
        await stages.transition(
            session,
            lead,
            target,
            TransitionSource.QUALIFIER,
            reason=f"qualifier: {result.output.next_best_action or result.output.intent}",
        )
    stored = dict(lead.qualification or {})
    stored.update(decision.qualification.model_dump(exclude_none=True))
    stored["signals"] = decision.signals.model_dump()
    lead.qualification = stored
    lead.need_summary = decision.need_summary
    lead.product_interest = list(decision.product_interest)
    lead.score = decision.score
    lead.bot_turns_without_progress = decision.bot_turns_without_progress


def _fill_run(
    run: QualifierRun,
    lead: Lead,
    decision: qd.QualifierDecision,
    result: QualifierResult,
    escalated: bool,
) -> None:
    run.output = result.output.model_dump(mode="json")
    run.proposed_stage = result.output.proposed_stage
    run.applied_stage = decision.final_stage.value if decision.final_stage else None
    run.rejected_reason = decision.rejected_reason
    run.triggers_fired = [h.code.value for h in decision.hits]
    run.score_after = lead.score
    run.escalated = escalated
    run.trace_id = result.trace_id
    run.model = result.model
    run.cost_usd = result.cost_usd


def _state(lead: Lead) -> qd.LeadState:
    stored: dict[str, Any] = dict(lead.qualification or {})
    known = {k: v for k, v in stored.items() if k in QUALIFICATION_FIELDS}
    signals = stored.get("signals") or {}
    return qd.LeadState(
        stage=Stage(lead.stage),
        score=lead.score,
        qualification=Qualification.model_validate(known),
        signals=LeadSignals.model_validate(
            {k: v for k, v in signals.items() if k in LeadSignals.model_fields}
        ),
        need_summary=lead.need_summary,
        product_interest=tuple(lead.product_interest or ()),
        bot_turns_without_progress=lead.bot_turns_without_progress,
    )


def _card(lead: Lead) -> dict[str, Any]:
    stored = dict(lead.qualification or {})
    return {
        "stage": lead.stage,
        "score": lead.score,
        "need_summary": lead.need_summary,
        "product_interest": list(lead.product_interest or []),
        "qualification": {k: v for k, v in stored.items() if k in QUALIFICATION_FIELDS},
    }


async def _last_trigger_id(session: AsyncSession, lead_id: int) -> int | None:
    stmt = (
        select(QualifierRun.trigger_message_id)
        .where(QualifierRun.lead_id == lead_id, QualifierRun.trigger_message_id.is_not(None))
        .order_by(QualifierRun.id.desc())
        .limit(1)
    )
    value: int | None = await session.scalar(stmt)
    return value


async def _last_price_quoted(session: AsyncSession, lead_id: int) -> bool:
    """Назвал ли бот цену из базы в последнем ответе агента (meta сообщения, ADR-0016)."""
    messages: Sequence[Message] = await repo.recent_messages(session, lead_id, 10)
    for message in reversed(messages):
        if message.role == "bot" and "action" in (message.meta or {}):
            return bool(message.meta.get("price_quoted"))
    return False


_LANGUAGES: dict[str, Language] = {"ru": "ru", "uz": "uz", "en": "en"}


def _lang(lead: Lead) -> Language:
    return _LANGUAGES.get(lead.language, "ru")
