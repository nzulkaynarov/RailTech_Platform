"""Узлы диалогового графа (SPEC §7.1). Данные — только через MCP-инструменты."""

import asyncio
from datetime import UTC, datetime
from typing import Any, Final

import structlog

from app.agents import prompts
from app.agents.dialog import customer
from app.agents.dialog.state import DialogState
from app.agents.dialog.tools import TOOLS, run_tools, tool_messages
from app.agents.llm import ChatCompleter, ChatResult
from app.agents.mcp_client import ToolCaller
from app.domain.business_hours import is_business_time
from app.domain.dialog_policy import Action, DecisionInput, decide
from app.domain.keywords import find_terms
from app.domain.stages import OwnerMode, Stage
from app.domain.text import drop_trailing_question, ends_with_question, limit_words
from app.schemas.settings import AppSettings, Language

logger = structlog.get_logger(__name__)

PROMPTS: Final = {"prospect": "dialog_prospect", "customer": "dialog_customer"}


def prompt_for(mode: str) -> str:
    return PROMPTS.get(mode, PROMPTS["prospect"])


ROLE_TAGS: Final = {"lead": "client", "bot": "assistant", "manager": "manager", "system": "system"}
# Встречный вопрос в конце — не чаще раза в QUESTION_EVERY ответов бота (тон, SPEC §7.1).
QUESTION_EVERY: Final = 3
KB_ATTEMPTS: Final = 2


class DialogNodes:
    def __init__(self, tools: ToolCaller, model: ChatCompleter, settings: AppSettings) -> None:
        self._tools = tools
        self._model = model
        self._settings = settings

    async def load_context(self, state: DialogState) -> dict[str, Any]:
        lead = await self._tools.call("crm", "get_lead_context", {}, state["context_token"])
        return {"lead": lead}

    async def retrieve(self, state: DialogState) -> dict[str, Any]:
        kb = await self._search_kb(state)
        docs = None
        if state["mode"] == "customer":
            docs = await customer.search(
                self._tools, state["text"], state["context_token"], self._settings
            )
        return {"kb": kb, "docs": docs}

    async def _search_kb(self, state: DialogState) -> dict[str, Any]:
        """Поиск kb-mcp: попытка с коротким таймаутом и одна повторная (аудит P0).

        Недоступный поиск не роняет ход: `decide` выберет честный fallback.
        """
        args = {"query": state["text"], "top_k": self._settings.kb.top_k}
        timeout = self._settings.kb.search_timeout_s
        for attempt in range(1, KB_ATTEMPTS + 1):
            try:
                found = await asyncio.wait_for(
                    self._tools.call("kb", "search_kb", args, state["context_token"]), timeout
                )
            except Exception as exc:  # noqa: BLE001 — таймаут, сеть, ошибка инструмента
                logger.warning(
                    "kb_search_failed",
                    lead_id=state["lead_id"],
                    attempt=attempt,
                    error=type(exc).__name__,
                )
                continue
            return dict(found or {})
        return {"hits": [], "best_score": None, "unavailable": True}

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
                document_match=customer.is_match(state["docs"]),
                document_requested=state["docs"] is not None,
                documents_found=len(state["docs"] or []),
                customer=state["mode"] == "customer",
                kb_unavailable=bool(kb.get("unavailable")),
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
        hours = self._settings.business_hours.domain()
        business = is_business_time(datetime.now(UTC), hours)
        return {
            "reply": self._settings.lead_notice(
                "handoff" if business else "off_hours", _lang(state)
            )
        }

    async def deliver_document(self, state: DialogState) -> dict[str, Any]:
        """Ровно один документ клиента: ссылка из docs-mcp, отправку файла делает бот."""
        doc = (state["docs"] or [{}])[0]
        link = await self._tools.call(
            "docs", "get_document_link", {"document_id": doc["document_id"]}, state["context_token"]
        )
        text = self._settings.texts.document_sent.get(_lang(state), title=str(link["title"]))
        return {"reply": text, "document": link}

    async def answer(self, state: DialogState) -> dict[str, Any]:
        if state["reason"] == "ack":
            # «Ок/спасибо» — короткий ответ из настроек, без модели и без встречного вопроса.
            return {"reply": self._settings.texts.smalltalk_ack.get(_lang(state))}
        messages = self._messages(state)
        tools = TOOLS if state["mode"] == "prospect" else [TOOLS[0], *customer.CUSTOMER_TOOLS]
        first = await self._model.complete(messages, tools=tools, name="dialog.answer")
        cost = first.cost_usd or 0.0
        outcome = None
        final = first
        if first.tool_calls:
            outcome = await run_tools(
                self._tools,
                first,
                tools,
                state["context_token"],
                state["lead_id"],
                self._settings.kb.search_timeout_s,
            )
            followup = [*messages, *tool_messages(first, outcome.outputs)]
            final = await self._model.complete(followup, name="dialog.answer.final")
            cost += final.cost_usd or 0.0
        reply = self._shape(state, final.text, outcome.request_number if outcome else None)
        return {
            "reply": reply,
            "llm": {**_llm_meta(final), "cost_usd": cost or None},
            "callback_requested": bool(outcome and outcome.callback),
            "service_request": bool(outcome and outcome.service),
        }

    def _shape(
        self, state: DialogState, text: str | None, request_number: int | None
    ) -> str | None:
        """Гарантии кода поверх ответа модели: тон, длина, номер запроса как в /request."""
        if not text:
            return None
        if state["reason"] == "smalltalk" or (
            not state["clarify"] and _recent_question(state["lead"] or {})
        ):
            text = drop_trailing_question(text)
        # Лимит длины — гарантия кода, промпт лишь просит (модель иногда превышает).
        reply = limit_words(text, self._settings.bot.max_words)
        if request_number is not None and str(request_number) not in reply:
            created = self._settings.texts.request_created.get(
                _lang(state), number=str(request_number)
            )
            reply = f"{reply}\n\n{created}"
        return reply

    def _messages(self, state: DialogState) -> list[dict[str, Any]]:
        lead = state["lead"] or {}
        kb = state["kb"] or {}
        bot = self._settings.bot
        extra = (
            {"documents": customer.documents_block(state["docs"])}
            if state["mode"] == "customer"
            else {"clarify_instruction": _clarify(state["clarify"])}
        )
        system = prompts.render(
            prompt_for(state["mode"]),
            **extra,
            company=self._settings.company.name,
            persona=bot.persona,
            language_name=prompts.LANGUAGE_NAMES[_lang(state)],
            max_words=str(bot.max_words),
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


def _recent_question(lead: dict[str, Any]) -> bool:
    """Бот уже спрашивал в одном из последних ответов — сейчас без встречного вопроса."""
    bot = [m["text"] for m in lead.get("history", []) if m.get("role") == "bot"]
    return any(ends_with_question(t) for t in bot[-(QUESTION_EVERY - 1) :])


def _llm_meta(result: ChatResult) -> dict[str, Any]:
    return {
        "model": result.model,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "latency_ms": result.latency_ms,
        "fallback": result.used_fallback,
    }
