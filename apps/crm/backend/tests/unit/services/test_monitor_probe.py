"""Часовая проверка моделей монитором: каждый платный запрос — в учёт `llm_usage` (purpose
`probe`), провайдер сверх лимита BudgetGuard не проверяется (отложено из PR #21)."""

from types import SimpleNamespace
from typing import Any, cast

import httpx2
from openai import APIConnectionError, APIStatusError

from app.domain.budget import Route
from app.integrations.llm_usage import UsageEvent
from app.services import models_status


class Raw:
    def __init__(self) -> None:
        self.headers = {"x-litellm-response-cost": "0.00002"}

    def parse(self) -> Any:
        usage = SimpleNamespace(prompt_tokens=8, completion_tokens=1)
        return SimpleNamespace(model="served", usage=usage)


class FakeLlm:
    def __init__(self, errors: dict[str, Exception] | None = None) -> None:
        self.errors = errors or {}
        self.calls: list[dict[str, Any]] = []
        create = SimpleNamespace(create=self.create)
        self.chat = SimpleNamespace(completions=SimpleNamespace(with_raw_response=create))

    async def create(self, **kwargs: Any) -> Raw:
        self.calls.append(kwargs)
        error = self.errors.get(kwargs["model"])
        if error is not None:
            raise error
        return Raw()


class Sink:
    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    async def record(self, event: UsageEvent) -> None:
        self.events.append(event)


class Guard:
    def __init__(self, over: set[str] | None = None) -> None:
        self.over = over or set()

    async def route(self, alias: str, *, allows_fallback: bool) -> Route:
        assert allows_fallback is False  # проверка идёт мимо резерва — резерв не подменяет
        return Route.UNAVAILABLE if alias in self.over else Route.PRIMARY


def _status_error(code: int, text: str) -> APIStatusError:
    request = httpx2.Request("POST", "http://litellm")
    return APIStatusError(text, response=httpx2.Response(code, request=request), body=None)


ALIASES = ("dialog-model", "fallback-model")


async def test_every_probe_call_is_recorded_as_probe() -> None:
    client, sink = FakeLlm(), Sink()
    result = await models_status.monitor_probe(cast(Any, client), ALIASES, sink, Guard())
    assert result == {"dialog-model": None, "fallback-model": None}
    assert [(e.purpose, e.alias, e.cost_usd) for e in sink.events] == [
        ("probe", "dialog-model", 0.00002),
        ("probe", "fallback-model", 0.00002),
    ]
    assert all(c["max_tokens"] == 1 for c in client.calls)
    # Без резерва LiteLLM (иначе сбой Claude скрыт ответом Gemini) и с тегами журнала расходов.
    assert [c["extra_body"] for c in client.calls] == [
        {
            "metadata": {"tags": ["system=crm", "feature=probe", f"model={alias}"]},
            "disable_fallbacks": True,
        }
        for alias in ALIASES
    ]


async def test_provider_over_limit_is_not_probed() -> None:
    client, sink = FakeLlm(), Sink()
    guard = Guard(over={"dialog-model"})
    result = await models_status.monitor_probe(cast(Any, client), ALIASES, sink, guard)
    assert [c["model"] for c in client.calls] == ["fallback-model"]
    assert "dialog-model" not in result  # состояние алерта не меняем — неизвестно
    assert [e.alias for e in sink.events] == ["fallback-model"]


async def test_provider_problem_reported_network_error_skipped() -> None:
    client = FakeLlm(
        {
            "dialog-model": _status_error(400, "Your credit balance is too low"),
            "fallback-model": APIConnectionError(request=httpx2.Request("POST", "http://x")),
        }
    )
    sink = Sink()
    result = await models_status.monitor_probe(cast(Any, client), ALIASES, sink, Guard())
    assert result["dialog-model"]  # «нет кредитов» — алерт
    assert "fallback-model" not in result
    assert sink.events == []  # ошибка LiteLLM не тарифицируется — строки учёта нет
