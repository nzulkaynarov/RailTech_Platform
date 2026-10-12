"""State machine стадий лида (SPEC §6.2). Решает код, модель только предлагает."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.domain.stages import Stage, TransitionSource

S = Stage
Src = TransitionSource

# Явная таблица разрешённых переходов: (из, в) -> допустимые источники.
_ALLOWED: Final[dict[tuple[Stage, Stage], frozenset[TransitionSource]]] = {
    (S.NEW, S.ENGAGED): frozenset({Src.QUALIFIER}),
    (S.ENGAGED, S.QUALIFIED): frozenset({Src.QUALIFIER}),
    **{
        (s, S.HANDOFF): frozenset({Src.TRIGGER})
        for s in (S.NEW, S.ENGAGED, S.QUALIFIED, S.UNRESPONSIVE)
    },
    (S.HANDOFF, S.IN_PROGRESS): frozenset({Src.USER}),
    # «Забрать» из CRM без эскалации (ADR-0012).
    **{
        (s, S.IN_PROGRESS): frozenset({Src.USER})
        for s in (S.NEW, S.ENGAGED, S.QUALIFIED, S.UNRESPONSIVE)
    },
    (S.HANDOFF, S.ENGAGED): frozenset({Src.USER}),
    (S.HANDOFF, S.QUALIFIED): frozenset({Src.USER}),
    (S.IN_PROGRESS, S.WON): frozenset({Src.USER}),
    (S.IN_PROGRESS, S.LOST): frozenset({Src.USER}),
    (S.IN_PROGRESS, S.ENGAGED): frozenset({Src.USER}),
    (S.IN_PROGRESS, S.QUALIFIED): frozenset({Src.USER}),
    (S.WON, S.CUSTOMER): frozenset({Src.USER, Src.SYSTEM}),
    # В handoff ждёт лид, а не мы: таймер «Не отвечает» его не трогает (ADR-0015).
    **{(s, S.UNRESPONSIVE): frozenset({Src.TIMER}) for s in (S.NEW, S.ENGAGED, S.QUALIFIED)},
    (S.UNRESPONSIVE, S.ENGAGED): frozenset({Src.SYSTEM}),
    # Выход из «Отказа» и повторная сделка клиента (ADR-0015).
    (S.LOST, S.ENGAGED): frozenset({Src.SYSTEM}),
    (S.LOST, S.IN_PROGRESS): frozenset({Src.USER}),
    (S.CUSTOMER, S.IN_PROGRESS): frozenset({Src.USER}),
    (S.LOST, S.CUSTOMER): frozenset({Src.SYSTEM}),
    # «Вернуть боту» повторной сделки: клиент остаётся клиентом (аудит 2026-10-12, P0-2).
    (S.IN_PROGRESS, S.CUSTOMER): frozenset({Src.USER}),
}

QUALIFIER_PROPOSABLE: Final = frozenset({S.ENGAGED, S.QUALIFIED})
RETURN_TO_BOT_STAGES: Final = frozenset({S.ENGAGED, S.QUALIFIED})


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    from_stage: Stage
    to_stage: Stage
    allowed: bool
    changed: bool
    reason: str | None = None


def decide(current: Stage, target: Stage, source: TransitionSource) -> TransitionDecision:
    """Разрешён ли переход; переход в ту же стадию — no-op, не ошибка."""
    if current == target:
        return TransitionDecision(current, target, allowed=True, changed=False)
    if source == Src.QUALIFIER and target not in QUALIFIER_PROPOSABLE:
        return _reject(
            current, target, f"qualifier may only propose engaged/qualified, got {target}"
        )
    sources = _ALLOWED.get((current, target))
    if sources is None:
        return _reject(current, target, f"transition {current} -> {target} is not allowed")
    if source not in sources:
        return _reject(current, target, f"source {source} may not move {current} -> {target}")
    return TransitionDecision(current, target, allowed=True, changed=True)


def qualifier_path(current: Stage, proposed: Stage) -> tuple[tuple[Stage, ...], str | None]:
    """Стадии, через которые проходит лид по предложению квалификатора.

    `new → qualified` проходит через `engaged` (оба ребра разрешены квалификатору):
    первое же сообщение может содержать всё для квалификации. Возвращает путь и
    причину отказа (путь пуст, если переход не нужен или отклонён).
    """
    if current == S.NEW and proposed == S.QUALIFIED:
        return (S.ENGAGED, S.QUALIFIED), None
    decision = decide(current, proposed, Src.QUALIFIER)
    if not decision.allowed:
        return (), decision.reason
    return ((proposed,) if decision.changed else ()), None


def stage_before_handoff(history: Sequence[tuple[Stage, Stage]]) -> Stage:
    """Стадия для «Вернуть боту»: откуда лид пришёл в handoff/in_progress (иначе engaged).

    Последний вход из «Клиента» («Новая сделка») возвращает в «Клиента»: повторная продажа
    не делает клиента снова лидом.
    """
    for from_stage, to_stage in reversed(history):
        if to_stage not in (S.HANDOFF, S.IN_PROGRESS):
            continue
        if from_stage == S.CUSTOMER:
            return S.CUSTOMER
        if from_stage in RETURN_TO_BOT_STAGES:
            return from_stage
    return S.ENGAGED


def _reject(current: Stage, target: Stage, reason: str) -> TransitionDecision:
    return TransitionDecision(current, target, allowed=False, changed=False, reason=reason)
