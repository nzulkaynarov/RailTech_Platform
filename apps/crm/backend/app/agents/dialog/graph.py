"""Диалоговый агент на LangGraph (SPEC §7.1).

load_context → (owner_mode=bot?) → retrieve → decide → answer | fallback | handoff | silent.
Персистентность сообщений, пробелов KB и счётчиков — у вызывающего сервиса
(`services/conversation.py`); граф только решает, что ответить.
"""

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer

from app.agents import prompts
from app.agents.dialog.nodes import DialogNodes, prompt_for
from app.agents.dialog.state import DialogResult, DialogState
from app.agents.llm import ChatCompleter
from app.agents.mcp_client import ToolCaller
from app.domain.dialog_policy import Action
from app.integrations import langfuse as lf
from app.schemas.settings import AppSettings


def build_graph(nodes: DialogNodes, checkpointer: Checkpointer = None) -> Any:
    # Any: обобщённые типы StateGraph не выводятся mypy для TypedDict-состояния.
    graph: Any = StateGraph(DialogState)
    graph.add_node("load_context", nodes.load_context)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("decide", nodes.decide)
    graph.add_node("silent", nodes.silent)
    graph.add_node("answer", nodes.answer)
    graph.add_node("fallback", nodes.fallback)
    graph.add_node("handoff", nodes.handoff)
    graph.add_node("deliver_document", nodes.deliver_document)
    graph.add_edge(START, "load_context")
    graph.add_conditional_edges("load_context", nodes.route_after_context, ["retrieve", "silent"])
    graph.add_edge("retrieve", "decide")
    graph.add_conditional_edges(
        "decide",
        nodes.route,
        {
            Action.ANSWER.value: "answer",
            Action.FALLBACK.value: "fallback",
            Action.HANDOFF.value: "handoff",
            Action.SILENT.value: "silent",
            Action.DELIVER_DOCUMENT.value: "deliver_document",
        },
    )
    for name in ("silent", "answer", "fallback", "handoff", "deliver_document"):
        graph.add_edge(name, END)
    return graph.compile(checkpointer=checkpointer)


class DialogAgent:
    def __init__(
        self, tools: ToolCaller, model: ChatCompleter, checkpointer: Checkpointer = None
    ) -> None:
        self._tools = tools
        self._model = model
        self._checkpointer = checkpointer

    async def run(
        self,
        *,
        lead_id: int,
        text: str,
        language: str,
        context_token: str,
        settings: AppSettings,
        human_requested: bool = False,
        stage: str = "new",
        mode: str = "prospect",
    ) -> DialogResult:
        graph = build_graph(DialogNodes(self._tools, self._model, settings), self._checkpointer)
        initial: DialogState = {
            "lead_id": lead_id,
            "text": text,
            "language": language,
            "mode": mode,
            "context_token": context_token,
            "human_requested": human_requested,
            "lead": None,
            "kb": None,
            "action": None,
            "clarify": False,
            "reason": "",
            "reply": None,
            "llm": None,
            "callback_requested": False,
            "docs": None,
            "document": None,
            "service_request": False,
        }
        config = {"configurable": {"thread_id": f"lead-{lead_id}"}}
        with lf.trace("dialog.turn", lead_id=lead_id, mode=mode, stage=stage, input=text):
            state = await graph.ainvoke(initial, config=config)
            trace_id = lf.current_trace_id()
        return _result(state, trace_id)


def _result(state: dict[str, Any], trace_id: str | None) -> DialogResult:
    kb = state.get("kb") or {}
    hits = [{"chunk_id": h["chunk_id"], "score": h.get("similarity")} for h in kb.get("hits", [])]
    return DialogResult(
        action=Action(state.get("action") or Action.SILENT.value),
        reply=state.get("reply"),
        reason=state.get("reason", ""),
        best_score=kb.get("best_score"),
        kb_hits=hits,
        llm=state.get("llm"),
        callback_requested=bool(state.get("callback_requested")),
        trace_id=trace_id,
        prompt_version=prompts.version(prompt_for(state.get("mode", "prospect"))),
        document=state.get("document"),
        service_request=bool(state.get("service_request")),
        mode=state.get("mode", "prospect"),
    )
