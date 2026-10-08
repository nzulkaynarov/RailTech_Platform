"""Квалификатор на LangGraph (SPEC §7.2): classify → validate (один повтор).

Модель `qualifier-model` возвращает `QualifierOutput` (structured output).
Решения о стадии, score и эскалации принимает код (`domain/qualifier_decision`).
"""

import json
from dataclasses import dataclass
from typing import Any, Final, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agents import prompts
from app.agents.llm import ChatCompleter
from app.agents.schema import response_format
from app.domain.qualification import QualifierOutput
from app.integrations import langfuse as lf

PROMPT: Final = "qualifier"
MAX_ATTEMPTS: Final = 2
ROLE_TAGS: Final = {"lead": "client", "bot": "assistant", "manager": "manager", "system": "system"}
FORMAT: Final = response_format(QualifierOutput, "qualifier_output")


class QualifierFailedError(Exception):
    """Модель не вернула валидный вывод за отведённые попытки."""


@dataclass(frozen=True, slots=True)
class QualifierInput:
    lead_id: int
    company: str
    products: list[tuple[str, str]]
    card: dict[str, Any]
    transcript: list[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class QualifierResult:
    output: QualifierOutput
    model: str
    cost_usd: float | None
    trace_id: str | None
    prompt_version: str


class _State(TypedDict):
    messages: list[dict[str, Any]]
    attempts: int
    output: dict[str, Any] | None
    error: str | None
    model: str
    cost_usd: float


class QualifierAgent:
    def __init__(self, model: ChatCompleter) -> None:
        self._model = model
        graph: Any = StateGraph(_State)
        graph.add_node("classify", self._classify)
        graph.add_edge(START, "classify")
        graph.add_conditional_edges("classify", self._route, ["classify", END])
        self._graph = graph.compile()

    async def run(self, data: QualifierInput) -> QualifierResult:
        state: _State = {
            "messages": build_messages(data),
            "attempts": 0,
            "output": None,
            "error": None,
            "model": "",
            "cost_usd": 0.0,
        }
        stage = str(data.card.get("stage", ""))
        with lf.trace(
            "qualifier.run", lead_id=data.lead_id, mode="qualifier", stage=stage, input=None
        ):
            final = await self._graph.ainvoke(state)
            trace_id = lf.current_trace_id()
        if final["output"] is None:
            raise QualifierFailedError(final["error"] or "no output")
        return QualifierResult(
            output=QualifierOutput.model_validate(final["output"]),
            model=final["model"],
            cost_usd=final["cost_usd"] or None,
            trace_id=trace_id,
            prompt_version=prompts.version(PROMPT),
        )

    async def _classify(self, state: _State) -> dict[str, Any]:
        result = await self._model.complete(
            state["messages"], response_format=FORMAT, name="qualifier.classify"
        )
        update: dict[str, Any] = {
            "attempts": state["attempts"] + 1,
            "model": result.model,
            "cost_usd": state["cost_usd"] + (result.cost_usd or 0.0),
        }
        try:
            parsed = QualifierOutput.model_validate(json.loads(result.text))
        except (json.JSONDecodeError, ValidationError) as exc:
            return {**update, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        return {**update, "output": parsed.model_dump(mode="json"), "error": None}

    def _route(self, state: _State) -> str:
        if state["output"] is None and state["attempts"] < MAX_ATTEMPTS:
            return "classify"
        return END


def build_messages(data: QualifierInput) -> list[dict[str, Any]]:
    system = prompts.render(
        PROMPT,
        company=data.company,
        products=prompts.xml_items("product", [({"key": k}, name) for k, name in data.products]),
        card=prompts.xml_escape(json.dumps(data.card, ensure_ascii=False)),
        transcript=prompts.xml_items(
            "message",
            [({"from": ROLE_TAGS.get(role, "system")}, text) for role, text in data.transcript],
        ),
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "Заполни карточку лида по переписке."},
    ]
