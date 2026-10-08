"""Узлы диалогового графа (SPEC §7.1). Данные — только через MCP-инструменты."""

import json
from datetime import UTC, datetime
from typing import Any, Final

import structlog

from app.agents import prompts
from app.agents.dialog.state import DialogState
from app.agents.llm import ChatCompleter, ChatResult
from app.agents.mcp_client import ToolCaller
from app.domain.business_hours import is_business_time
from app.domain.dialog_policy import Action, DecisionInput, decide
from app.domain.keywords import find_terms
from app.domain.stages import OwnerMode, Stage
from app.schemas.settings import AppSettings, Language

logger = structlog.get_logger(__name__)

PROMPT: Final = "dialog_prospect"
ROLE_TAGS: Final = {"lead": "client", "bot": "assistant", "manager": "manager", "system": "system"}

TOOLS: Final[list[dict[str, Any]]] = [
    {
        "type": "function",
        "function": {
            "name": "request_callback",
            "description": (
                "Клиент сам попросил, чтобы с ним связались. "
                "Укажи удобное время, если он его назвал."
            ),
            "parameters": {
                "type": "object",
                "properties": {"preferred_time": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_qualification",
            "description": "Записать сведения, которые клиент сам сообщил о себе и задаче.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "object",
                        "properties": {
                            "company": {"type": "string"},
                            "company_size": {"type": "string"},
                            "region": {"type": "string"},
                            "timeline": {"type": "string", "enum": ["<1m", "<3m", "<12m", ">12m"]},
                            "decision_role": {
                                "type": "string",
                                "enum": ["decision_maker", "influencer", "researcher"],
                            },
                            "budget_hint": {"type": "string"},
                        },
                        "additionalProperties": False,
                    }
                },
                "required": ["patch"],
                "additionalProperties": False,
            },
        },
    },
]


class DialogNodes:
    def __init__(self, tools: ToolCaller, model: ChatCompleter, settings: AppSettings) -> None:
        self._tools = tools
        self._model = model
        self._settings = settings

    async def load_context(self, state: DialogState) -> dict[str, Any]:
        lead = await self._tools.call("crm", "get_lead_context", {}, state["context_token"])
        return {"lead": lead}

    async def retrieve(self, state: DialogState) -> dict[str, Any]:
        args = {"query": state["text"], "top_k": self._settings.kb.top_k}
        kb = await self._tools.call("kb", "search_kb", args, state["context_token"])
        return {"kb": kb}

    def decide(self, state: DialogState) -> dict[str, Any]:
        lead = state["lead"] or {}
        kb = state["kb"] or {}
        text = state["text"]
        human = state["human_requested"] or bool(
            find_terms(text, self._settings.escalation.human_request_terms)
        )
        decision = decide(
            DecisionInput(
                owner_mode=OwnerMode(lead.get("owner_mode", "bot")),
                stage=Stage(lead.get("stage", "new")),
                text=text,
                human_requested=human,
                stop_word_hit=bool(find_terms(text, self._settings.stop_words.terms)),
                best_score=kb.get("best_score"),
                min_score=self._settings.kb.min_score,
                need_known=bool(lead.get("need_summary")),
            )
        )
        return {
            "action": decision.action.value,
            "clarify": decision.clarify,
            "reason": decision.reason,
        }

    def route(self, state: DialogState) -> str:
        return state["action"] or Action.SILENT.value

    def route_after_context(self, state: DialogState) -> str:
        lead = state["lead"] or {}
        return "retrieve" if lead.get("owner_mode", "bot") == "bot" else "silent"

    def silent(self, _state: DialogState) -> dict[str, Any]:
        return {"action": Action.SILENT.value, "reply": None}

    def fallback(self, state: DialogState) -> dict[str, Any]:
        return {"reply": self._settings.texts.fallback.get(_lang(state))}

    def handoff(self, state: DialogState) -> dict[str, Any]:
        texts = self._settings.texts
        hours = self._settings.business_hours.domain()
        text = texts.handoff if is_business_time(datetime.now(UTC), hours) else texts.off_hours
        return {"reply": text.get(_lang(state))}

    async def answer(self, state: DialogState) -> dict[str, Any]:
        messages = self._messages(state)
        tools = TOOLS if state["mode"] == "prospect" else TOOLS[:1]
        first = await self._model.complete(messages, tools=tools, name="dialog.answer")
        callback = False
        cost = first.cost_usd or 0.0
        if first.tool_calls:
            callback = await self._run_tools(state, first)
            followup = [*messages, *_tool_messages(first)]
            final = await self._model.complete(followup, name="dialog.answer.final")
            cost += final.cost_usd or 0.0
        else:
            final = first
        return {
            "reply": final.text or None,
            "llm": {**_llm_meta(final), "cost_usd": cost or None},
            "callback_requested": callback,
        }

    async def _run_tools(self, state: DialogState, result: ChatResult) -> bool:
        callback = False
        for call in result.tool_calls:
            if call.name not in {t["function"]["name"] for t in TOOLS}:
                continue
            try:
                await self._tools.call("crm", call.name, call.arguments, state["context_token"])
            except Exception:  # noqa: BLE001 — ответ клиенту важнее записи сигнала
                logger.warning("dialog_tool_failed", tool=call.name, lead_id=state["lead_id"])
                continue
            callback = callback or call.name == "request_callback"
        return callback

    def _messages(self, state: DialogState) -> list[dict[str, Any]]:
        lead = state["lead"] or {}
        kb = state["kb"] or {}
        bot = self._settings.bot
        system = prompts.render(
            PROMPT,
            company=self._settings.company.name,
            persona=bot.persona,
            language_name=prompts.LANGUAGE_NAMES[_lang(state)],
            max_words=str(bot.max_words),
            clarify_instruction=_clarify(state["clarify"]),
            notes=prompts.xml_items("note", [({}, n) for n in lead.get("notes", [])]),
            kb=prompts.xml_items(
                "fragment",
                [
                    (
                        {"title": h["document_title"], "section": h.get("heading_path") or ""},
                        h["content"],
                    )
                    for h in kb.get("hits", [])
                ],
            ),
            history=prompts.xml_items(
                "message",
                [
                    ({"from": ROLE_TAGS.get(m["role"], "system")}, m["text"])
                    for m in lead.get("history", [])[:-1]
                ],
            ),
        )
        user = f"<user_message>{prompts.xml_escape(state['text'])}</user_message>"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _lang(state: DialogState) -> Language:
    language = state["language"]
    return language if language in ("ru", "uz", "en") else "ru"  # type: ignore[return-value]


def _clarify(clarify: bool) -> str:
    if not clarify:
        return ""
    return (
        "# Уточнение\nПотребность клиента пока не ясна. Ответь на вопрос по фрагментам "
        "и задай ровно один короткий уточняющий вопрос о задаче клиента."
    )


def _tool_messages(result: ChatResult) -> list[dict[str, Any]]:
    assistant = {
        "role": "assistant",
        "content": result.text or None,
        "tool_calls": [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": _json(c.arguments)},
            }
            for c in result.tool_calls
        ],
    }
    outputs = [
        {"role": "tool", "tool_call_id": c.id, "content": '{"ok": true}'} for c in result.tool_calls
    ]
    return [assistant, *outputs]


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _llm_meta(result: ChatResult) -> dict[str, Any]:
    return {
        "model": result.model,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "latency_ms": result.latency_ms,
        "fallback": result.used_fallback,
    }
