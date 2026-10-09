"""План эскалации по сработавшим триггерам (SPEC §8.1–8.2).

Одна открытая эскалация на лида: новые триггеры дописываются, приоритет
повышается, пост в канале редактируется. Побочные эффекты выполняет сервис.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from app.domain.stages import OwnerMode, Stage
from app.domain.triggers import Priority, TriggerCode, TriggerHit, max_priority

HANDOFF_FROM: Final = frozenset({Stage.NEW, Stage.ENGAGED, Stage.QUALIFIED, Stage.UNRESPONSIVE})

ChannelAction = Literal["post", "edit", "none"]
LeadText = Literal["handoff", "off_hours"]


@dataclass(frozen=True, slots=True)
class OpenEscalation:
    reason_codes: tuple[TriggerCode, ...]
    priority: Priority


@dataclass(frozen=True, slots=True)
class EscalationPlan:
    reason_codes: tuple[TriggerCode, ...]
    priority: Priority
    is_new: bool
    move_to_handoff: bool
    pause_bot: bool
    lead_text: LeadText | None
    channel_action: ChannelAction


def plan(
    hits: Sequence[TriggerHit],
    *,
    stage: Stage,
    owner_mode: OwnerMode,
    open_escalation: OpenEscalation | None,
    business_time: bool,
) -> EscalationPlan | None:
    """None — эскалация не нужна (нет триггеров или лида уже ведёт человек)."""
    if not hits or owner_mode == OwnerMode.HUMAN:
        return None
    previous = open_escalation.reason_codes if open_escalation else ()
    codes = tuple(dict.fromkeys([*previous, *(h.code for h in hits)]))
    priorities = [h.priority for h in hits] + (
        [open_escalation.priority] if open_escalation else []
    )
    priority = max_priority(priorities)
    assert priority is not None  # noqa: S101 — hits не пуст
    is_new = open_escalation is None
    changed = open_escalation is None or codes != previous or priority != open_escalation.priority
    # info — сведения для команды: бот продолжает отвечать (ADR-0015). Передача человеку —
    # когда эскалация впервые становится срочной (новая warm/hot или повышение с info).
    urgent = priority != Priority.INFO
    was_urgent = open_escalation is not None and open_escalation.priority != Priority.INFO
    hand_over = urgent and not was_urgent
    return EscalationPlan(
        reason_codes=codes,
        priority=priority,
        is_new=is_new,
        move_to_handoff=urgent and stage in HANDOFF_FROM,
        pause_bot=urgent and owner_mode == OwnerMode.BOT,
        lead_text=("handoff" if business_time else "off_hours") if hand_over else None,
        channel_action="post" if is_new else ("edit" if changed else "none"),
    )
