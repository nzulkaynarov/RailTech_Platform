"""Каркас evals без моделей: golden-кейсы валидны, оценщик работает на записанных ответах.

Записанные ответы (`evals/recorded/*.json`) — форма ответа сервисов; модели здесь не вызываются.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from evals import runner
from evals.cases import load_intake_cases, load_match_cases, parse_intake_case, parse_match_case
from evals.scoring import score_intake, score_match, summarize

RECORDED = Path(__file__).resolve().parent.parent / "recorded"


def _recorded(name: str) -> dict:
    data = json.loads((RECORDED / name).read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


def test_golden_sets_load_and_are_unique():
    intake = load_intake_cases()
    match = load_match_cases()
    assert len(intake) >= 10 and len(match) >= 6
    assert any(case.kind == "csv" for case in intake) and any(case.kind == "text" for case in intake)
    assert any(line.expect_product_id is None for case in match for line in case.lines), "нужен кейс «ничего»"
    quick = [case.id for case in (*intake, *match) if "quick" in case.tags]
    assert len(quick) >= 6


def test_golden_data_is_neutral_and_has_no_company_names():
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in (Path(runner.__file__).parent / "golden").glob("*.yaml")
    )
    for banned in ("вагон", "рельс", "тормозн", "автосцеп", "ООО", "АО ", "LLC"):
        assert banned.lower() not in text.lower(), banned


@pytest.mark.parametrize("case_id", sorted(_recorded("intake.json")))
def test_recorded_intake_answers_pass(case_id):
    case = next(case for case in load_intake_cases() if case.id == case_id)
    score = score_intake(case, _recorded("intake.json")[case_id])
    assert score.passed, score.failures


@pytest.mark.parametrize("case_id", sorted(_recorded("match.json")))
def test_recorded_match_answers_pass(case_id):
    case = next(case for case in load_match_cases() if case.id == case_id)
    score = score_match(case, _recorded("match.json")[case_id])
    assert score.passed, score.failures


def test_intake_scorer_catches_wrong_quantity_unit_missing_and_invented_lines():
    case = next(case for case in load_intake_cases() if case.id == "text-two-goods-ru")
    good = _recorded("intake.json")["text-two-goods-ru"]

    wrong_qty = [dict(good[0], quantity=5), good[1]]
    assert not score_intake(case, wrong_qty).passed

    wrong_unit = [dict(good[0], unit="кг"), good[1]]
    assert any("unit" in failure for failure in score_intake(case, wrong_unit).failures)

    missing = [good[0]]
    assert "missing line" in score_intake(case, missing).failures[0]

    invented = [*good, {"name": "Каска защитная", "quantity": 1, "unit": "шт"}]
    score = score_intake(case, invented)
    assert not score.passed and "extra" in score.failures[-1]


def test_empty_request_case_rejects_any_line():
    case = next(case for case in load_intake_cases() if case.id == "text-not-a-request")
    assert score_intake(case, []).passed
    assert not score_intake(case, [{"name": "График работы", "quantity": 1}]).passed


def test_match_scorer_wrong_top_and_confident_wrong_answer_fail():
    case = next(case for case in load_match_cases() if case.id == "exact-name-ru")
    wrong = [{"line_index": 0, "candidates": [{"product_id": 102, "confidence": 0.9}]}]
    assert not score_match(case, wrong).passed
    assert not score_match(case, []).passed

    nothing = next(case for case in load_match_cases() if case.id == "nothing-fits")
    confident_wrong = [{"line_index": 0, "candidates": [{"product_id": 501, "confidence": 0.95}]}]
    assert not score_match(nothing, confident_wrong).passed


def test_summary():
    intake = {case.id: case for case in load_intake_cases()}
    recorded = _recorded("intake.json")
    scores = [score_intake(intake[case_id], items) for case_id, items in recorded.items()]
    scores.append(score_intake(intake["text-english"], []))
    summary = summarize(scores)
    assert summary["cases"] == len(recorded) + 1
    assert summary["passed"] == len(recorded)
    assert list(summary["failed"]) == ["text-english"]


@pytest.mark.parametrize(
    "raw, message",
    [
        ({"id": "Bad Id", "kind": "text", "input": "x", "lines": []}, "kebab-case"),
        ({"id": "a", "kind": "pdf", "input": "x", "lines": []}, "kind"),
        ({"id": "a", "kind": "text", "input": "x", "lines": [{"name_any": []}]}, "name_any"),
        ({"id": "a", "kind": "text", "input": "x", "lines": [], "typo": 1}, "unknown fields"),
        ({"id": "a", "kind": "text", "input": "x", "lines": [{"name_any": ["x"], "quantity": 0}]}, "quantity"),
    ],
)
def test_broken_intake_case_is_rejected(raw, message):
    with pytest.raises(ValueError, match=message):
        parse_intake_case(raw)


def test_match_expectation_must_be_a_candidate():
    raw = {"id": "a", "lines": [{"name": "x", "candidates": [{"id": 1, "name": "y"}], "expect": 2}]}
    with pytest.raises(ValueError, match="not among"):
        parse_match_case(raw)


def test_case_selection(monkeypatch):
    cases = load_match_cases()
    monkeypatch.setenv("EVAL_CASES", "nothing-fits, exact-name-ru")
    assert {case.id for case in runner.selected(cases)} == {"nothing-fits", "exact-name-ru"}
    monkeypatch.delenv("EVAL_CASES")
    assert len(runner.selected(cases)) == len(cases)


@pytest.mark.django_db
def test_runner_scores_through_the_service_with_a_fake_gateway(fake_gateway):
    """Цепочка runner → сервис → шлюз собрана правильно (фейк вместо модели, без денег)."""
    case = next(case for case in load_match_cases() if case.id == "exact-name-ru")
    fake_gateway.reply_json(
        {"matches": [{"line_index": 0, "candidates": [{"product_id": 101, "confidence": 0.9, "reason": "ok"}]}]},
        cost="0.0005",
    )
    before = runner.spent()

    score = runner.run_match_case(case)

    assert score.passed
    assert runner.spent() - before == Decimal("0.0005")
    metadata = fake_gateway.last_body["metadata"]
    assert metadata["session_id"] == "eval-exact-name-ru" and "feature=match" in metadata["tags"]
