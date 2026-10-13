"""Pure-logic tests for the Deal FSM transition matrix.

No DB access: exercises the ALLOWED_STAGE_TRANSITIONS map and
get_allowed_transitions() helper that gate every deal stage change.
"""

from crm.services import ALLOWED_STAGE_TRANSITIONS, get_allowed_transitions

# Canonical set of stage codes the FSM operates over.
KNOWN_STAGES = {
    "DRAFT",
    "KYC_PENDING",
    "RFQ_OPEN",
    "SOURCING",
    "CALCULATING",
    "QUOTE_SENT",
    "CONTRACT_SIGNED",
    "CLOSED_WON",
    "CLOSED_LOST",
}


class TestTransitionMatrixIntegrity:
    def test_all_targets_are_known_stages(self):
        for source, targets in ALLOWED_STAGE_TRANSITIONS.items():
            for target in targets:
                assert target in KNOWN_STAGES, f"{source} -> unknown target {target}"

    def test_all_sources_are_known_stages(self):
        for source in ALLOWED_STAGE_TRANSITIONS:
            assert source in KNOWN_STAGES

    def test_no_self_loops(self):
        for source, targets in ALLOWED_STAGE_TRANSITIONS.items():
            assert source not in targets, f"{source} lists itself as a target"

    def test_targets_have_no_duplicates(self):
        for source, targets in ALLOWED_STAGE_TRANSITIONS.items():
            assert len(targets) == len(set(targets)), f"{source} has duplicate targets"


class TestGetAllowedTransitions:
    def test_unknown_stage_returns_empty(self):
        assert get_allowed_transitions("NOT_A_STAGE") == []

    def test_quote_sent_can_advance_to_contract(self):
        assert "CONTRACT_SIGNED" in get_allowed_transitions("QUOTE_SENT")

    def test_quote_sent_can_revert_to_calculating(self):
        assert "CALCULATING" in get_allowed_transitions("QUOTE_SENT")

    def test_draft_cannot_jump_to_closed_won(self):
        assert "CLOSED_WON" not in get_allowed_transitions("DRAFT")

    def test_contract_signed_cannot_jump_to_draft(self):
        assert "DRAFT" not in get_allowed_transitions("CONTRACT_SIGNED")

    def test_closed_won_only_reopens_to_contract(self):
        assert get_allowed_transitions("CLOSED_WON") == ["CONTRACT_SIGNED"]

    def test_every_non_terminal_can_reach_closed_lost(self):
        for stage in ("DRAFT", "KYC_PENDING", "RFQ_OPEN", "SOURCING", "CALCULATING", "QUOTE_SENT"):
            assert "CLOSED_LOST" in get_allowed_transitions(stage)
