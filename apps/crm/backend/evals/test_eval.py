"""Evals диалогового агента на golden-кейсах (SPEC §12, PLAN Фаза 2).

Нужны реальные модели (LiteLLM с ключами) и демо-KB в Postgres (`make kb-demo`).
Запуск: `make eval` (в контейнере worker dev-стенда) или CI `eval-gate` (Фаза 7).
Детерминированные проверки — кодом: решение, язык, числа, утечки; faithfulness —
judge-модель. Пороги Фазы 2: faithfulness ≥ 0.9, выдуманных чисел 0.
"""

import json
import statistics
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest

from app.agents import prompts
from app.agents.dialog.graph import DialogAgent
from app.agents.llm import ChatModel
from app.config import Settings
from app.container import Container
from app.domain.language import detect_language
from app.domain.numbers import unsupported_numbers
from app.schemas.settings import AppSettings
from app.services.kb.search import KbSearchService
from evals.golden import GoldenCase, load_cases

pytestmark = pytest.mark.eval

CASES = load_cases()
FAITHFULNESS_GATE = 0.9
JUDGE_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "faithfulness",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "score": {"type": "number"},
                "unsupported": {"type": "array", "items": {"type": "string"}},
                "comment": {"type": "string"},
            },
            "required": ["score", "unsupported", "comment"],
            "additionalProperties": False,
        },
    },
}


@dataclass
class Outcome:
    case_id: str
    faithfulness: float | None
    invented_numbers: list[str]


RESULTS: list[Outcome] = []


class EvalTools:
    """crm — синтетический лид из кейса; kb — реальный поиск по демо-KB."""

    def __init__(self, case: GoldenCase, search: KbSearchService) -> None:
        self._case = case
        self._search = search
        self.kb_payload: dict[str, Any] = {}
        self.tool_calls: list[str] = []

    async def call(self, server: str, tool: str, args: dict[str, Any], context: str) -> Any:
        if tool == "get_lead_context":
            history = [t.model_dump() for t in self._case.history]
            return {
                "lead_id": 0,
                "language": self._case.language,
                "stage": self._case.stage,
                "owner_mode": "bot",
                "need_summary": self._case.need_summary,
                "notes": [],
                "history": [*history, {"role": "lead", "text": self._case.message}],
            }
        if tool == "search_kb":
            result = await self._search.search(
                args["query"], top_k=args.get("top_k", 6), language=self._case.language
            )
            self.kb_payload = {
                "hits": [
                    {
                        "chunk_id": h.chunk_id,
                        "document_title": h.document_title,
                        "heading_path": h.heading_path,
                        "content": h.content,
                        "similarity": h.similarity,
                    }
                    for h in result.hits
                ],
                "best_score": result.best_score,
            }
            return self.kb_payload
        self.tool_calls.append(tool)
        return {"ok": True}


@pytest.fixture(scope="module")
async def container() -> AsyncIterator[Container]:
    settings = Settings()
    if not settings.litellm_api_key.get_secret_value():
        pytest.fail("LITELLM_API_KEY не задан: evals нужны реальные модели (make eval)")
    c = Container(settings)
    yield c
    await c.engine.dispose()


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
async def test_golden_case(case: GoldenCase, container: Container) -> None:
    tools = EvalTools(case, KbSearchService(container.session_factory, container.embedder))
    agent = DialogAgent(tools, ChatModel(container.llm, "dialog-model"))
    result = await agent.run(
        lead_id=0,
        text=case.message,
        language=case.language,
        context_token="eval",
        settings=AppSettings(),
        stage=case.stage,
    )
    expect = case.expect
    assert result.action.value in expect.actions, result.reason
    reply = result.reply or ""
    if expect.reply_language:
        assert detect_language(reply, default=expect.reply_language) == expect.reply_language
    assert len(reply.split()) <= expect.max_words
    lowered = reply.lower()
    assert not [s for s in expect.must_not_include if s.lower() in lowered]
    if expect.must_include_any:
        assert any(s.lower() in lowered for s in expect.must_include_any), reply
    fragments = [h["content"] for h in tools.kb_payload.get("hits", [])]
    if expect.kb_document:
        titles = {h["document_title"] for h in tools.kb_payload.get("hits", [])}
        assert expect.kb_document in titles
    invented = sorted(unsupported_numbers(reply, [*fragments, case.message]))
    score = None
    if result.action.value == "answer" and case.category != "smalltalk":
        score = await _judge(container, fragments, case.message, reply)
    RESULTS.append(Outcome(case.id, score, invented))
    assert invented == [], f"числа не из KB: {invented}"


async def _judge(container: Container, fragments: list[str], question: str, answer: str) -> float:
    system = prompts.render(
        "judge_faithfulness",
        kb=prompts.xml_items("fragment", [({}, f) for f in fragments]),
        question=prompts.xml_escape(question),
        answer=prompts.xml_escape(answer),
    )
    judge = ChatModel(container.llm, "judge-model", max_tokens=512)
    verdict = await judge.complete(
        [{"role": "user", "content": system}], response_format=JUDGE_SCHEMA, name="eval.judge"
    )
    return float(json.loads(verdict.text)["score"])


def test_zz_summary_gate() -> None:
    """Итог по набору: средняя faithfulness и выдуманные числа (запускается последним)."""
    scored = [r.faithfulness for r in RESULTS if r.faithfulness is not None]
    invented = {r.case_id: r.invented_numbers for r in RESULTS if r.invented_numbers}
    mean = statistics.fmean(scored) if scored else 0.0
    print(json.dumps({"cases": len(RESULTS), "faithfulness": mean, "invented": invented}))
    assert scored, "нет ни одного оценённого ответа"
    assert mean >= FAITHFULNESS_GATE
    assert invented == {}
