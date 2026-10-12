"""Устойчивость и честность диалогового агента (аудит 2026-10-12): сбой KB, реальные
результаты инструментов, номер запроса, тон и ответ на «спасибо» без модели."""

import asyncio
import json
from typing import Any

import pytest

from app.agents.dialog.graph import DialogAgent
from app.agents.dialog.state import DialogResult
from app.agents.llm import ToolCall
from app.domain.dialog_policy import Action
from app.schemas.settings import AppSettings, KbSettings
from tests.unit.agents.fakes import FakeTools, ReplayModel, kb, lead, reply

SETTINGS = AppSettings(kb=KbSettings(search_timeout_s=1))


class FlakyTools(FakeTools):
    """search_kb падает `kb_failures` раз; инструменты из `broken` всегда падают."""

    def __init__(
        self,
        lead_ctx: dict[str, Any],
        kb_result: dict[str, Any],
        kb_failures: int = 0,
        broken: frozenset[str] = frozenset(),
        results: dict[str, Any] | None = None,
        hang: bool = False,
    ) -> None:
        super().__init__(lead_ctx, kb_result)
        self.kb_failures = kb_failures
        self.broken = broken
        self.results = results or {}
        self.hang = hang

    async def call(self, server: str, tool: str, args: dict[str, Any], context: str) -> Any:
        if tool == "search_kb" and self.kb_failures > 0:
            self.kb_failures -= 1
            self.calls.append((server, tool, args))
            if self.hang:
                await asyncio.sleep(5)
            raise TimeoutError("kb-mcp read timeout")
        if tool in self.broken:
            self.calls.append((server, tool, args))
            raise RuntimeError("crm-mcp down")
        if tool in self.results:
            self.calls.append((server, tool, args))
            return self.results[tool]
        return await super().call(server, tool, args, context)


async def run(
    tools: FakeTools,
    model: ReplayModel,
    text: str = "Что входит в тариф Старт?",
    mode: str = "prospect",
    settings: AppSettings = SETTINGS,
) -> DialogResult:
    return await DialogAgent(tools, model).run(
        lead_id=1, text=text, language="ru", context_token="t", settings=settings, mode=mode
    )


def kb_searches(tools: FakeTools) -> int:
    return sum(1 for c in tools.calls if c[1] == "search_kb")


async def test_kb_timeout_is_retried_once_and_then_answers() -> None:
    tools = FlakyTools(lead(), kb(0.8), kb_failures=1)
    model = ReplayModel(reply("Тариф Старт включает одну кассу."))
    result = await run(tools, model)
    assert kb_searches(tools) == 2
    assert result.action == Action.ANSWER


async def test_kb_unavailable_gives_honest_fallback_not_apology() -> None:
    tools = FlakyTools(lead(), kb(0.8), kb_failures=2)
    model = ReplayModel()
    result = await run(tools, model)
    assert kb_searches(tools) == 2
    assert (result.action, result.reason) == (Action.FALLBACK, "kb_unavailable")
    assert result.reply == SETTINGS.texts.fallback.ru
    assert model.requests == []


async def test_hanging_kb_is_cut_by_timeout() -> None:
    tools = FlakyTools(lead(), kb(0.8), kb_failures=2, hang=True)
    result = await asyncio.wait_for(run(tools, ReplayModel()), timeout=4)
    assert result.reason == "kb_unavailable"


async def test_failed_tool_is_reported_to_the_model_as_failed() -> None:
    call = ToolCall(id="c1", name="request_callback", arguments={})
    tools = FlakyTools(lead(), kb(0.8), broken=frozenset({"request_callback"}))
    model = ReplayModel(reply("", call), reply("Не получилось оформить, напишите /human."))
    result = await run(tools, model, "Позвоните мне по тарифу Старт")
    assert not result.callback_requested
    tool_reply = json.loads(model.requests[1][-1]["content"])
    assert tool_reply["ok"] is False


async def test_disallowed_tool_is_reported_as_not_allowed() -> None:
    call = ToolCall(id="c1", name="create_service_request", arguments={"summary": "x"})
    tools = FakeTools(lead(), kb(0.8))
    model = ReplayModel(reply("", call), reply("Ответ."))
    result = await run(tools, model)  # prospect: сервисный запрос недоступен
    assert not result.service_request
    assert json.loads(model.requests[1][-1]["content"])["error"] == "not_allowed"
    assert all(c[1] != "create_service_request" for c in tools.calls)


async def test_service_request_number_matches_request_command() -> None:
    call = ToolCall(id="c1", name="create_service_request", arguments={"summary": "Касса"})
    results = {"create_service_request": {"ok": True, "service_request_id": 42}}
    tools = FlakyTools(lead(customer=True), kb(0.8), results=results)
    model = ReplayModel(reply("", call), reply("Передал ваш запрос менеджеру."))
    result = await run(tools, model, "Касса не печатает чеки", mode="customer")
    assert result.service_request
    assert json.loads(model.requests[1][-1]["content"]) == {"ok": True, "request_number": 42}
    assert result.reply is not None
    assert "№42" in result.reply


async def test_service_request_number_not_duplicated_when_model_cites_it() -> None:
    call = ToolCall(id="c1", name="create_service_request", arguments={"summary": "Касса"})
    results = {"create_service_request": {"ok": True, "service_request_id": 7}}
    tools = FlakyTools(lead(customer=True), kb(0.8), results=results)
    model = ReplayModel(reply("", call), reply("Запрос №7 передан менеджеру."))
    result = await run(tools, model, "Касса не печатает чеки", mode="customer")
    assert result.reply == "Запрос №7 передан менеджеру."


@pytest.mark.parametrize("text", ["Спасибо!", "ок", "Понятно", "rahmat", "Thanks"])
async def test_ack_is_answered_without_model(text: str) -> None:
    tools, model = FakeTools(lead(), kb(0.2)), ReplayModel()
    result = await run(tools, model, text)
    assert (result.action, result.reason) == (Action.ANSWER, "ack")
    assert result.reply == SETTINGS.texts.smalltalk_ack.ru
    assert model.requests == []


async def test_no_trailing_question_right_after_a_bot_question() -> None:
    history = [
        {"role": "bot", "text": "Тариф Старт включает кассу. Сколько у вас точек?"},
        {"role": "lead", "text": "Что входит в тариф Старт?"},
    ]
    tools = FakeTools(lead(history=history), kb(0.8))
    model = ReplayModel(reply("Тариф Старт включает одну кассу. Нужна ли вам доставка?"))
    result = await run(tools, model)
    assert result.reply == "Тариф Старт включает одну кассу."


async def test_question_allowed_when_bot_has_not_asked_recently() -> None:
    history = [{"role": "bot", "text": "Здравствуйте."}, {"role": "lead", "text": "вопрос"}]
    tools = FakeTools(lead(history=history), kb(0.8))
    model = ReplayModel(reply("Тариф Старт включает одну кассу. Сколько у вас точек?"))
    result = await run(tools, model)
    assert result.reply is not None
    assert result.reply.endswith("?")


async def test_default_threshold_treats_noise_scores_as_not_in_kb() -> None:
    # Аудит: бессмыслица набирала 0.596–0.676 — это «нет в базе», а не ответ модели.
    tools, model = FakeTools(lead(), kb(0.676)), ReplayModel()
    result = await run(tools, model, "фыва олдж пролд", settings=AppSettings())
    assert result.action == Action.FALLBACK
    assert model.requests == []
