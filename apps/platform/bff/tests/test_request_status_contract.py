"""ПРАВДА-2: «В кабинете клиента» в карточке компании — то же слово, что в «Заявках» Кабинета.

Один источник — `packages/contracts/client-request-statuses.yaml`: Кабинет сверяет с ним i18n,
ERP — свою проекцию `request_status`, здесь — таблица BFF и список статусов.
"""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest
import yaml

from app.crm_clients_view import _CABINET_STATUS, cabinet_status_of, request_row
from app.schemas_crm_leads import RequestStatus

CONTRACT = yaml.safe_load(
    (
        Path(__file__).resolve().parents[4] / "packages/contracts/client-request-statuses.yaml"
    ).read_text(encoding="utf-8")
)


def _deal(external_stage: str | None, stage: str = "open") -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        erp_number="ЗВ-1",
        title="Т",
        request_summary="",
        stage=stage,
        external_stage=external_stage,
        request_urgency="normal",
        erp_request_status="done",
        erp_request_error=None,
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
        request_letter_file_id=None,
    )


def test_statuses_are_the_contract_statuses() -> None:
    assert set(get_args(RequestStatus)) == set(CONTRACT["statuses"])


def test_bff_table_is_the_contract_table() -> None:
    expected = dict(CONTRACT["by_external_stage"])
    assert {k: v for k, v in _CABINET_STATUS.items() if k is not None} == expected
    assert _CABINET_STATUS[None] == "new"  # событий ERP ещё не было


@pytest.mark.parametrize("stage", sorted(CONTRACT["by_external_stage"]))
def test_every_request_stage_has_the_cabinet_word(stage: str) -> None:
    deal = _deal(None if stage == "request" else stage, stage="lost" if stage == "lost" else "open")
    assert cabinet_status_of(deal) == CONTRACT["by_external_stage"][stage]  # type: ignore[arg-type]
    assert request_row(deal).cabinet_status == CONTRACT["by_external_stage"][stage]  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "stage", ["accepted", "contract", "invoiced", "paid", "fulfilment", "closing"]
)
def test_project_has_no_request_status(stage: str) -> None:
    assert cabinet_status_of(_deal(stage)) is None  # type: ignore[arg-type]
