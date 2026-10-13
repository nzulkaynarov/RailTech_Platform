"""Передача в бэк-офис и итог сделки из ERP (ADR-0022): таблица кейсов по обоим режимам."""

import pytest

from app.domain.backoffice import (
    ERP_OUTCOME_EVENTS,
    HANDOFF_FROM,
    BackofficeMode,
    backoffice_mode,
    decide_handoff,
    may_close_locally,
)
from app.domain.stage_machine import decide
from app.domain.stages import Stage as S
from app.domain.stages import TransitionSource as Src

LOCAL, ERP = BackofficeMode.LOCAL, BackofficeMode.ERP

# (стадия лида, режим) → передача разрешена. Без коннектора — только после «Сделка заключена»
# (как прежде); с коннектором — из работы менеджера, итог придёт из ERP.
HANDOFF = [
    (S.NEW, LOCAL, False),
    (S.ENGAGED, LOCAL, False),
    (S.QUALIFIED, LOCAL, False),
    (S.HANDOFF, LOCAL, False),
    (S.IN_PROGRESS, LOCAL, False),
    (S.WON, LOCAL, True),
    (S.LOST, LOCAL, False),
    (S.UNRESPONSIVE, LOCAL, False),
    (S.CUSTOMER, LOCAL, True),
    (S.NEW, ERP, False),
    (S.ENGAGED, ERP, False),
    (S.QUALIFIED, ERP, False),
    (S.HANDOFF, ERP, False),  # лид ждёт менеджера: сначала «Забрать», потом передача
    (S.IN_PROGRESS, ERP, True),
    (S.WON, ERP, True),  # закрыт в CRM до подключения ERP — передать всё равно можно
    (S.LOST, ERP, False),
    (S.UNRESPONSIVE, ERP, False),
    (S.CUSTOMER, ERP, True),
]


@pytest.mark.parametrize(("stage", "mode", "allowed"), HANDOFF)
def test_handoff_table(stage: S, mode: BackofficeMode, allowed: bool) -> None:
    decision = decide_handoff(stage, mode)
    assert decision.allowed is allowed
    assert decision.mode is mode
    assert decision.from_stage is stage
    if allowed:
        assert decision.changed
        assert decision.reason is None
        assert decision.call_erp is (mode is ERP)
    else:
        assert not decision.changed
        assert not decision.call_erp
        assert decision.reason


def test_handoff_table_covers_every_stage_in_both_modes() -> None:
    assert {(stage, mode) for stage, mode, _ in HANDOFF} == {
        (s, m) for s in S for m in BackofficeMode
    }
    assert {s for s, m, ok in HANDOFF if ok and m is LOCAL} == HANDOFF_FROM[LOCAL]
    assert {s for s, m, ok in HANDOFF if ok and m is ERP} == HANDOFF_FROM[ERP]


@pytest.mark.parametrize("mode", list(BackofficeMode))
def test_repeated_handoff_is_idempotent(mode: BackofficeMode) -> None:
    """Лид уже клиент той же компании: разрешено, но ничего не меняется и ERP не вызывается."""
    repeat = decide_handoff(S.CUSTOMER, mode, client_changed=False)
    assert repeat.allowed
    assert not repeat.changed
    assert not repeat.call_erp
    assert repeat.reason is None


@pytest.mark.parametrize("mode", list(BackofficeMode))
def test_customer_changing_company_is_a_real_handoff(mode: BackofficeMode) -> None:
    moved = decide_handoff(S.CUSTOMER, mode, client_changed=True)
    assert moved.allowed
    assert moved.changed
    assert moved.call_erp is (mode is ERP)


@pytest.mark.parametrize(
    ("stage", "mode"),
    [(s, m) for s in S for m in BackofficeMode if s is not S.CUSTOMER],
)
def test_client_changed_flag_matters_only_for_customers(stage: S, mode: BackofficeMode) -> None:
    assert decide_handoff(stage, mode, client_changed=False) == decide_handoff(stage, mode)


@pytest.mark.parametrize(("configured", "expected"), [(False, LOCAL), (True, ERP)])
def test_mode_follows_connector(configured: bool, expected: BackofficeMode) -> None:
    assert backoffice_mode(erp_connector_configured=configured) is expected


@pytest.mark.parametrize(
    ("mode", "outcome", "allowed"),
    [
        (LOCAL, "won", True),
        (LOCAL, "lost", True),
        # С коннектором выигрыш решает бэк-офис (`deal.won`), фронт-офис может только отказать.
        (ERP, "won", False),
        (ERP, "lost", True),
    ],
)
def test_may_close_locally(mode: BackofficeMode, outcome: str, allowed: bool) -> None:
    assert may_close_locally(mode, outcome) is allowed


@pytest.mark.parametrize("event", sorted(ERP_OUTCOME_EVENTS))
@pytest.mark.parametrize("stage", list(S))
@pytest.mark.parametrize("target", [S.WON, S.LOST, S.CUSTOMER, S.ENGAGED, S.IN_PROGRESS])
def test_erp_outcome_never_moves_the_lead(event: str, stage: S, target: S) -> None:
    """`deal.won`/`deal.lost` из ERP — только зеркало сделок; стадия лида остаётся."""
    assert event in ERP_OUTCOME_EVENTS
    decision = decide(stage, target, Src.ERP)
    assert not decision.changed
    assert decision.allowed is (stage is target)  # та же стадия — no-op, иначе отказ
    if stage is not target:
        assert decision.reason
        assert "erp" in decision.reason
