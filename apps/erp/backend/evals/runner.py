"""Прогон golden-кейса через настоящие сервисы ERP и шлюз LiteLLM (ПЛАТНО — только evals).

Модуль ничего не вызывает сам: его зовёт `evals/test_eval.py` под маркером `eval`, который
запускается только `make -C apps/erp eval-quick CONFIRM=yes` (согласие владельца на прогон).
Каждый кейс — свой `trace_scope` (`session_id = eval-<id>`): стоимость кейса берётся из ответа
шлюза, вызовы видны в Langfuse и в «Расходах» CRM с тегом `feature=…` как обычные вызовы ERP.
"""

from __future__ import annotations

import os
from decimal import Decimal

from ai.services.context import trace_scope
from ai.services.matching import Candidate, rank_candidates

from .cases import IntakeCase, MatchCase
from .scoring import CaseScore, score_intake, score_match

MAX_USD = Decimal(os.environ.get("EVAL_MAX_USD", "0.2"))
_spent = [Decimal("0")]


def spent() -> Decimal:
    return _spent[0]


def budget_left() -> bool:
    return _spent[0] < MAX_USD


def selected(cases: list) -> list:
    """`EVAL_CASES=id1,id2` — только перечисленные (eval-quick)."""
    wanted = {item.strip() for item in os.environ.get("EVAL_CASES", "").split(",") if item.strip()}
    return [case for case in cases if not wanted or case.id in wanted]


def run_intake_case(case: IntakeCase) -> CaseScore:
    from ai.services.compose import build_request_from_text
    from ai.services.intake import extract_request_items

    with trace_scope(f"eval-{case.id}", job_feature="eval") as trace:
        if case.kind == "text":
            items = build_request_from_text(case.input, attach_candidates=False)["items"]
        else:
            items = extract_request_items(case.input.encode("utf-8"), f"{case.id}.csv", retries=0)
    _spent[0] += trace.cost_usd
    return score_intake(case, items)


def run_match_case(case: MatchCase) -> CaseScore:
    lines = [
        {"name": line.name, "name_canonical": line.name_canonical, "mpn": line.mpn, "gost_drawing": line.gost_drawing}
        for line in case.lines
    ]
    shortlists = {
        index: [Candidate(c.id, c.name, c.sku, c.gost_drawing) for c in line.candidates]
        for index, line in enumerate(case.lines)
    }
    with trace_scope(f"eval-{case.id}", job_feature="eval") as trace:
        ranked = rank_candidates(lines, shortlists, top_k=3)
    _spent[0] += trace.cost_usd
    return score_match(case, ranked)
