import pytest

from app.domain.escalation import OpenEscalation, plan
from app.domain.stages import OwnerMode, Stage
from app.domain.triggers import Priority, TriggerCode, TriggerHit

HOT = TriggerHit(TriggerCode.HUMAN_REQUESTED, Priority.HOT)
WARM = TriggerHit(TriggerCode.HIGH_SCORE, Priority.WARM)


def test_no_hits_no_plan() -> None:
    assert (
        plan(
            [],
            stage=Stage.ENGAGED,
            owner_mode=OwnerMode.BOT,
            open_escalation=None,
            business_time=True,
        )
        is None
    )


def test_human_owner_no_plan() -> None:
    assert (
        plan(
            [HOT],
            stage=Stage.IN_PROGRESS,
            owner_mode=OwnerMode.HUMAN,
            open_escalation=None,
            business_time=True,
        )
        is None
    )


@pytest.mark.parametrize(
    ("stage", "handoff"),
    [
        (Stage.NEW, True),
        (Stage.ENGAGED, True),
        (Stage.QUALIFIED, True),
        (Stage.UNRESPONSIVE, True),
        (Stage.CUSTOMER, False),
        (Stage.HANDOFF, False),
    ],
)
def test_new_escalation(stage: Stage, handoff: bool) -> None:
    result = plan(
        [WARM], stage=stage, owner_mode=OwnerMode.BOT, open_escalation=None, business_time=True
    )
    assert result is not None
    assert result.is_new
    assert result.move_to_handoff is handoff
    assert result.pause_bot
    assert result.lead_text == "handoff"
    assert result.channel_action == "post"


def test_off_hours_text() -> None:
    result = plan(
        [HOT], stage=Stage.NEW, owner_mode=OwnerMode.BOT, open_escalation=None, business_time=False
    )
    assert result is not None
    assert result.lead_text == "off_hours"


def test_merge_raises_priority_and_edits_post() -> None:
    existing = OpenEscalation(reason_codes=(TriggerCode.HIGH_SCORE,), priority=Priority.WARM)
    result = plan(
        [HOT],
        stage=Stage.HANDOFF,
        owner_mode=OwnerMode.PAUSED,
        open_escalation=existing,
        business_time=True,
    )
    assert result is not None
    assert result.reason_codes == (TriggerCode.HIGH_SCORE, TriggerCode.HUMAN_REQUESTED)
    assert result.priority == Priority.HOT
    assert not result.is_new
    assert result.lead_text is None
    assert result.channel_action == "edit"
    assert not result.pause_bot


def test_merge_without_changes_does_nothing_visible() -> None:
    existing = OpenEscalation(reason_codes=(TriggerCode.HIGH_SCORE,), priority=Priority.WARM)
    result = plan(
        [WARM],
        stage=Stage.HANDOFF,
        owner_mode=OwnerMode.PAUSED,
        open_escalation=existing,
        business_time=True,
    )
    assert result is not None
    assert result.channel_action == "none"


INFO = TriggerHit(TriggerCode.SERVICE_REQUEST, Priority.INFO)


@pytest.mark.parametrize("stage", [Stage.ENGAGED, Stage.CUSTOMER])
def test_info_escalation_keeps_bot_talking(stage: Stage) -> None:
    """ADR-0015: info — сведения для команды; бот не замолкает, лиду не пишем «передаю»."""
    result = plan(
        [INFO], stage=stage, owner_mode=OwnerMode.BOT, open_escalation=None, business_time=True
    )
    assert result is not None
    assert result.channel_action == "post"
    assert not result.pause_bot
    assert not result.move_to_handoff
    assert result.lead_text is None


def test_info_upgraded_to_hot_starts_full_handoff() -> None:
    existing = OpenEscalation(reason_codes=(TriggerCode.SERVICE_REQUEST,), priority=Priority.INFO)
    result = plan(
        [HOT],
        stage=Stage.ENGAGED,
        owner_mode=OwnerMode.BOT,
        open_escalation=existing,
        business_time=True,
    )
    assert result is not None
    assert not result.is_new
    assert result.priority == Priority.HOT
    assert result.pause_bot
    assert result.move_to_handoff
    assert result.lead_text == "handoff"
    assert result.channel_action == "edit"
