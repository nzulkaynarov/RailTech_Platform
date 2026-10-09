"""«Сухой прогон» правил эскалации (PLAN Фаза 5): что изменится на последних 50 диалогах.

Для каждого из 50 последних лидов берётся последний прогон квалификатора и
триггеры пересчитываются кодом при текущих и предлагаемых настройках. Пороги
(score, уверенность квалификатора) и отключение триггеров пересчитываются точно;
триггеры по фактам, которые не хранятся в прогоне (цена без ответа в KB,
конкурент, «нет прогресса»), учитываются так, как сработали тогда.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.qualification import QualifierOutput
from app.domain.triggers import TriggerCode, TriggerSettings, TriggerSignals, evaluate
from app.models.qualification import QualifierRun

DIALOGS: Final = 50
REPLAYED_AS_IS: Final = frozenset(
    {
        TriggerCode.PRICE_OR_CONTRACT_ASKED,
        TriggerCode.COMPETITOR_MENTIONED,
        TriggerCode.NO_PROGRESS,
    }
)


@dataclass(frozen=True, slots=True)
class DryRunRow:
    run_id: int
    lead_id: int
    at: datetime
    current: list[str]
    candidate: list[str]


@dataclass
class DryRunReport:
    dialogs: int = 0
    escalated_current: int = 0
    escalated_candidate: int = 0
    by_code_current: dict[str, int] = field(default_factory=dict)
    by_code_candidate: dict[str, int] = field(default_factory=dict)
    changed: list[DryRunRow] = field(default_factory=list)


def codes_for(run: QualifierRun, output: QualifierOutput, cfg: TriggerSettings) -> list[str]:
    crossed = run.score_before < cfg.high_score_threshold <= run.score_after
    signals = TriggerSignals(
        intent=output.intent,
        sentiment=output.sentiment,
        kb_best_score=1.0,  # цена без ответа в KB — повторяется по факту срабатывания ниже
        score=run.score_after if crossed else 0,
        recommend_escalation=output.recommend_escalation,
        confidence=output.confidence,
    )
    codes = {h.code for h in evaluate(signals, cfg)}
    fired = {
        TriggerCode(c) for c in run.triggers_fired or [] if c in TriggerCode.__members__.values()
    }
    codes |= {c for c in fired & REPLAYED_AS_IS if c not in cfg.disabled}
    return sorted(c.value for c in codes)


async def latest_runs(session: AsyncSession, dialogs: int = DIALOGS) -> list[QualifierRun]:
    latest = (
        select(func.max(QualifierRun.id).label("id"))
        .where(QualifierRun.output.is_not(None))
        .group_by(QualifierRun.lead_id)
        .order_by(func.max(QualifierRun.id).desc())
        .limit(dialogs)
        .subquery()
    )
    stmt = (
        select(QualifierRun)
        .join(latest, latest.c.id == QualifierRun.id)
        .order_by(QualifierRun.id.desc())
    )
    return list((await session.scalars(stmt)).all())


def compare(
    runs: list[QualifierRun], current: TriggerSettings, candidate: TriggerSettings
) -> DryRunReport:
    report = DryRunReport()
    by_current: Counter[str] = Counter()
    by_candidate: Counter[str] = Counter()
    for run in runs:
        try:
            output = QualifierOutput.model_validate(run.output)
        except ValidationError:
            continue
        before, after = codes_for(run, output, current), codes_for(run, output, candidate)
        report.dialogs += 1
        report.escalated_current += bool(before)
        report.escalated_candidate += bool(after)
        by_current.update(before)
        by_candidate.update(after)
        if before != after:
            report.changed.append(DryRunRow(run.id, run.lead_id, run.created_at, before, after))
    report.by_code_current, report.by_code_candidate = dict(by_current), dict(by_candidate)
    return report
