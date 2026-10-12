"""ChatModel: стоимость из заголовка LiteLLM и откат на fallback-model."""

from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from openai import APIConnectionError

from app.agents.llm import ChatModel, LlmUnavailableError
from app.integrations.llm_usage import UsageEvent, current_lead_id, lead_scope


def response(text: str, model: str) -> Any:
    message = SimpleNamespace(content=text, tool_calls=None)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage, model=model)


class Raw:
    def __init__(self, parsed: Any, headers: dict[str, str]) -> None:
        self._parsed = parsed
        self.headers = headers

    def parse(self) -> Any:
        return self._parsed


class FakeClient:
    def __init__(self, failing: set[str], cost: str | None = "0.0012") -> None:
        self.failing = failing
        self.cost = cost
        self.calls: list[str] = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=self.create))
        )

    async def create(self, **kwargs: Any) -> Raw:
        alias = kwargs["model"]
        self.calls.append(alias)
        if alias in self.failing:
            raise APIConnectionError(request=httpx2.Request("POST", "http://litellm"))
        headers = {"x-litellm-response-cost": self.cost} if self.cost else {}
        return Raw(response("ok", f"{alias}-served"), headers)


async def test_cost_is_read_from_litellm_header() -> None:
    model = ChatModel(FakeClient(set()), "dialog-model")  # type: ignore[arg-type]
    result = await model.complete([{"role": "user", "content": "hi"}])
    assert result.cost_usd == pytest.approx(0.0012)
    assert (result.text, result.used_fallback) == ("ok", False)


async def test_falls_back_when_primary_fails() -> None:
    client = FakeClient({"dialog-model"}, cost=None)
    result = await ChatModel(client, "dialog-model").complete([])  # type: ignore[arg-type]
    assert client.calls == ["dialog-model", "fallback-model"]
    assert result.used_fallback
    assert result.cost_usd is None


async def test_raises_when_both_fail() -> None:
    client = FakeClient({"dialog-model", "fallback-model"})
    with pytest.raises(LlmUnavailableError):
        await ChatModel(client, "dialog-model").complete([])  # type: ignore[arg-type]


class Sink:
    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    async def record(self, event: UsageEvent) -> None:
        self.events.append(event)


async def test_every_call_is_recorded_with_purpose_and_lead() -> None:
    sink = Sink()
    client = FakeClient({"dialog-model"})
    model = ChatModel(client, "dialog-model", usage=sink)  # type: ignore[arg-type]
    with lead_scope(42):
        assert current_lead_id() == 42
        await model.complete([])
    (event,) = sink.events
    assert (event.purpose, event.alias) == ("dialog", "fallback-model")
    assert event.model == "fallback-model-served"
    assert (event.input_tokens, event.output_tokens) == (10, 5)
    assert event.cost_usd == pytest.approx(0.0012)
    assert current_lead_id() is None


@pytest.mark.parametrize(
    ("alias", "purpose"),
    [
        ("dialog-model", "dialog"),
        ("qualifier-model", "qualifier"),
        ("judge-model", "judge"),
        ("fallback-model", "fallback"),
    ],
)
async def test_purpose_follows_alias(alias: Any, purpose: str) -> None:
    sink = Sink()
    await ChatModel(FakeClient(set()), alias, usage=sink).complete([])  # type: ignore[arg-type]
    assert sink.events[0].purpose == purpose


async def test_finish_reason_and_max_tokens_are_passed_through() -> None:
    """Оборванный лимитом ответ виден вызывающему (квалификатор не парсит обрезанный JSON)."""
    sent: dict[str, Any] = {}

    class Truncating(FakeClient):
        async def create(self, **kwargs: Any) -> Raw:
            sent.update(kwargs)
            parsed = response('{"intent": "pri', "served")
            parsed.choices[0].finish_reason = "length"
            return Raw(parsed, {})

    model = ChatModel(Truncating(set()), "qualifier-model", max_tokens=4096)  # type: ignore[arg-type]
    result = await model.complete([{"role": "user", "content": "hi"}])
    assert result.finish_reason == "length"
    assert sent["max_tokens"] == 4096
