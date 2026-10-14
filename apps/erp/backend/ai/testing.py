"""Фейковый шлюз LiteLLM для тестов: подменяет `ai.services.gateway._transport`.

Тесты ERP никогда не ходят в сеть и не тратят деньги: корневой conftest блокирует настоящий
транспорт, а фикстура `fake_gateway` ставит этот фейк с очередью заготовленных ответов в формате
OpenAI-совместимого API шлюза. Каждый запрос сохраняется — тест проверяет тело (алиас, теги,
промпт, `response_format`, `metadata`), а не только результат.
"""

from __future__ import annotations

import json

import httpx
from ai.services.gateway import COST_HEADER, TransportResponse


class UnexpectedGatewayCall(AssertionError):
    pass


class FakeGateway:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self._queue: list[object] = []

    # ── заготовки ответов (в порядке вызовов) ──────────────────────────────
    def reply_json(self, data: dict, *, cost: str | None = "0.0001", finish_reason: str = "stop", tokens=(10, 20)):
        return self.reply_text(
            json.dumps(data, ensure_ascii=False), cost=cost, finish_reason=finish_reason, tokens=tokens
        )

    def reply_text(self, text: str, *, cost: str | None = "0.0001", finish_reason: str = "stop", tokens=(10, 20)):
        payload = {
            "choices": [
                {"index": 0, "finish_reason": finish_reason, "message": {"role": "assistant", "content": text}}
            ],
            "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]},
        }
        headers = {COST_HEADER: cost} if cost is not None else {}
        self._queue.append(TransportResponse(200, headers, payload))
        return self

    def reply_refusal(self, reason: str = "declined"):
        payload = {
            "choices": [
                {"finish_reason": "stop", "message": {"role": "assistant", "content": None, "refusal": reason}}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 0},
        }
        self._queue.append(TransportResponse(200, {}, payload))
        return self

    def reply_http_error(self, status: int = 500, error_type: str = "internal_server_error"):
        self._queue.append(TransportResponse(status, {}, {"error": {"type": error_type, "message": "boom"}}))
        return self

    def reply_budget_exceeded(self):
        return self.reply_http_error(400, "budget_exceeded")

    def reply_transport_error(self):
        self._queue.append(httpx.ConnectError("gateway down"))
        return self

    # ── транспорт ─────────────────────────────────────────────────────────
    def __call__(self, url: str, body: dict, headers: dict, timeout: float) -> TransportResponse:
        self.requests.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        if not self._queue:
            raise UnexpectedGatewayCall(f"unexpected gateway call #{len(self.requests)} (model={body.get('model')})")
        reply = self._queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    @property
    def last_body(self) -> dict:
        return self.requests[-1]["body"]

    @property
    def calls(self) -> int:
        return len(self.requests)

    def user_text(self, index: int = -1) -> str:
        """Текстовые блоки сообщения `user` запроса — для проверок «данные — не в промпте»."""
        content = self.requests[index]["body"]["messages"][1]["content"]
        return "\n".join(block.get("text", "") for block in content if block.get("type") == "text")


def blocked_transport(url, body, headers, timeout):  # pragma: no cover - срабатывает только на ошибке теста
    raise UnexpectedGatewayCall("real LiteLLM call attempted in tests — use the fake_gateway fixture")


class _BodySink(list):
    """Список запросов фейка, который заодно складывает тела во внешний список теста."""

    def __init__(self, sink: list):
        super().__init__()
        self._sink = sink

    def append(self, item):
        super().append(item)
        self._sink.append(item["body"])


def install_fake_gateway(monkeypatch, sink: list | None = None) -> FakeGateway:
    """Фейковый шлюз без фикстуры (для хелперов тестов): ИИ включён, тела запросов — в `sink`."""
    from django.conf import settings

    gateway = FakeGateway()
    if sink is not None:
        gateway.requests = _BodySink(sink)
    monkeypatch.setattr(settings, "AI_IMPORT_ENABLED", True)
    monkeypatch.setattr(settings, "LITELLM_BASE_URL", "http://litellm.test")
    monkeypatch.setattr(settings, "LITELLM_API_KEY", "sk-erp-test")
    monkeypatch.setattr(settings, "AI_MAX_RETRIES", 0)
    monkeypatch.setattr("ai.services.gateway._transport", gateway)
    return gateway
