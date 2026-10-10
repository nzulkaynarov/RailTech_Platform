"""Evals квалификатора и правил эскалации (PLAN Фаза 3, SPEC §12).

Модель (`qualifier-model`) заполняет карточку, решения — код (`domain/`).
Метрики на наборе: escalation precision ≥ 0.8, recall ≥ 0.9, stage accuracy ≥ 0.85.
Запуск: `make eval` (нужны ключи моделей; БД не нужна).
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio

from app.agents.llm import ChatModel
from app.agents.qualifier.graph import QualifierAgent, QualifierInput
from app.config import Settings
from app.domain import qualifier_decision as qd
from app.domain.keywords import find_terms
from app.domain.qualification import LeadSignals, Qualification
from app.domain.stages import Stage
from app.domain.triggers import evaluate
from app.integrations.litellm import make_client
from app.schemas.settings import AppSettings, TermsSettings
from evals import budget, report
from evals.qualifier_cases import QualifierCase, load_products, load_qualifier_cases, turn_signals

pytestmark = pytest.mark.eval
# Один цикл событий на модуль: клиенты LiteLLM и пул БД живут весь модуль,
# иначе pytest-asyncio 1.x даёт ScopeMismatch / «Event loop is closed».
MODULE_LOOP = pytest.mark.asyncio(loop_scope="module")

CASES = budget.selected(load_qualifier_cases())
PRODUCTS = load_products()
CFG = AppSettings(competitors=TermsSettings(terms=["Glonass-Track", "Wialon"]))
# Пороги релиза SPEC §12 (eval-gate в CI, Фаза 7).
GATES = {"precision": 0.85, "recall": 0.95, "stage_accuracy": 0.85}


@dataclass
class Outcome:
    case_id: str
    expected_escalate: bool
    escalated: bool
    stage_ok: bool
    triggers: list[str]


RESULTS: list[Outcome] = []


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def agent() -> AsyncIterator[QualifierAgent]:
    settings = Settings()
    if not settings.litellm_api_key.get_secret_value():
        pytest.fail("LITELLM_API_KEY не задан: evals нужны реальные модели (make eval)")
    client = make_client(settings)
    yield QualifierAgent(ChatModel(client, "qualifier-model"))
    await client.close()  # иначе незакрытые сокеты к LiteLLM роняют pytest (filterwarnings=error)


@MODULE_LOOP
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
async def test_qualifier_case(case: QualifierCase, agent: QualifierAgent) -> None:
    data = QualifierInput(
        lead_id=0,
        company=CFG.company.name,
        products=PRODUCTS,
        card={"stage": case.stage, "score": case.score},
        transcript=list(case.transcript),
    )
    budget.guard()
    result = await agent.run(data)
    budget.add(result.cost_usd)
    state = qd.LeadState(
        stage=Stage(case.stage),
        score=case.score,
        qualification=Qualification(),
        signals=LeadSignals(),
        need_summary=None,
        product_interest=(),
        bot_turns_without_progress=case.bot_turns_without_progress,
    )
    last_lead = next(t for r, t in reversed(case.transcript) if r == "lead")
    facts = qd.TurnFacts(
        price_quoted=case.price_quoted,
        competitor_mentioned=bool(_terms(last_lead)),
        known_products={k for k, _ in PRODUCTS},
    )
    decision = qd.decide(
        state, result.output, facts, CFG.escalation.triggers(), CFG.qualification.criteria()
    )
    turn_hits = evaluate(turn_signals(case, CFG), CFG.escalation.triggers())
    codes = [h.code.value for h in (*turn_hits, *decision.hits)]
    stage = (decision.final_stage or Stage(case.stage)).value
    RESULTS.append(
        Outcome(case.id, case.expect.escalate, bool(codes), stage == case.expect.stage, codes)
    )
    assert bool(codes) == case.expect.escalate, f"triggers={codes}, output={result.output}"
    assert set(case.expect.triggers) <= set(codes), codes
    assert stage == case.expect.stage, result.output.model_dump_json()


def _terms(text: str) -> list[str]:
    return find_terms(text, CFG.competitors.terms)


def test_zz_qualifier_summary_gate() -> None:
    assert not budget.exhausted(), "лимит расходов исчерпан — прогон неполный (EVAL_MAX_USD)"
    tp = sum(r.escalated and r.expected_escalate for r in RESULTS)
    fp = sum(r.escalated and not r.expected_escalate for r in RESULTS)
    fn = sum(not r.escalated and r.expected_escalate for r in RESULTS)
    metrics = {
        "cases": len(RESULTS),
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "stage_accuracy": sum(r.stage_ok for r in RESULTS) / len(RESULTS) if RESULTS else 0.0,
    }
    failed = [r.case_id for r in RESULTS if r.escalated != r.expected_escalate or not r.stage_ok]
    report.write("qualifier", {"metrics": metrics, "gates": GATES, "failed": failed})
    print(json.dumps(metrics))
    assert RESULTS, "нет результатов"
    for name, gate in GATES.items():
        assert metrics[name] >= gate, f"{name}={metrics[name]:.2f} < {gate}"
