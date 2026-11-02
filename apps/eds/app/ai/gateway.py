"""Клиент EDS к моделям — LiteLLM Proxy по алиасам (ADR-0005; образец — `apps/erp/backend/ai/services/gateway.py`).

Прямого SDK провайдера нет: OpenAI-совместимый `POST {LITELLM_BASE_URL}/v1/chat/completions` своим виртуальным ключом
EDS (`EDS_LITELLM_API_KEY`, бюджет на ключе — `ai-key-sync`). Что стоит за алиасом — решает LiteLLM; код знает только
функцию → алиас (`FUNCTION_ALIASES`, новых алиасов EDS не заводит). Каждый вызов несёт `metadata.tags`
(`system=eds`, `feature`, `model`) — строки EDS сами попадают в «Расходы» консоли; `trace_*` — трейс Langfuse пишет шлюз
колбэком ключа, вход в трейс не копируется (`mask_input`): в модель уходит маскированный текст или скан письма.

Структурный вывод — `response_format: json_schema`; ошибка — результат со статусом, исключений наружу нет.
"""

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import httpx
import structlog

from app.config import Settings

log = structlog.get_logger(__name__)

INTAKE_MODEL: Final = "intake-model"
# Функция → алиас. Новая функция без строки здесь не позовёт модель (KeyError — ошибка кода, а не тихий выбор модели).
FUNCTION_ALIASES: Final[dict[str, str]] = {
    "letter_intake": INTAKE_MODEL,  # письмо организации (PDF-текст или скан) → поля карточки входящего
}
FALLBACK_ALIAS: Final = "fallback-model"
CHAT_PATH: Final = "/v1/chat/completions"
COST_HEADER: Final = "x-litellm-response-cost"
PROMPTS: Final = Path(__file__).parent / "prompts"

# Транспорт HTTP: тесты подменяют его `httpx.MockTransport` (CONVENTIONS.md §6 п. 3 — мокать границу).
TRANSPORT: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str

    @property
    def version(self) -> str:
        """Версия промпта — первые 12 знаков SHA-256 текста файла (как в CRM и ERP)."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:12]


@lru_cache
def load_prompt(name: str) -> Prompt:
    return Prompt(name=name, text=(PROMPTS / f"{name}.md").read_text(encoding="utf-8"))


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal | None = None


@dataclass
class Result:
    status: str  # ok | error | refusal | invalid | budget
    data: dict[str, Any] | None = None
    error_code: str = ""
    usage: Usage = field(default_factory=Usage)


def available(settings: Settings) -> bool:
    return bool(settings.litellm_api_key.get_secret_value())


def body_for(
    *, function: str, prompt: Prompt, user_content: list[dict[str, Any]], schema: dict[str, Any], max_tokens: int,
    user_id: int, session_id: str,
) -> dict[str, Any]:  # fmt: skip
    alias = FUNCTION_ALIASES[function]
    return {
        "model": alias,
        "messages": [{"role": "system", "content": prompt.text}, {"role": "user", "content": user_content}],
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": prompt.name, "schema": schema, "strict": True},
        },
        "metadata": {
            "tags": ["system=eds", f"feature={function}", f"model={alias}"],
            "trace_name": f"eds.{function}",
            "generation_name": f"eds.{function}",
            "session_id": session_id,
            "trace_user_id": f"eds-staff-{user_id}",
            "trace_metadata": {"system": "eds", "prompt": prompt.name, "prompt_version": prompt.version},
            "mask_input": True,
        },
    }


def _usage(response: httpx.Response, payload: dict[str, Any]) -> Usage:
    raw = payload.get("usage") or {}
    try:
        cost = Decimal(response.headers.get(COST_HEADER) or "") if response.headers.get(COST_HEADER) else None
    except InvalidOperation:
        cost = None
    return Usage(int(raw.get("prompt_tokens") or 0), int(raw.get("completion_tokens") or 0), cost)


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()


def interpret(response: httpx.Response) -> Result:
    """Ответ шлюза → результат. Без исключений."""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return Result("error", error_code="bad_response")
    usage = _usage(response, payload)
    error = payload.get("error")
    if response.status_code >= 400:
        kind = str(error.get("type") or "") if isinstance(error, dict) else ""
        status = "budget" if kind.lower() == "budget_exceeded" else "error"
        return Result(status, error_code=f"http_{response.status_code}", usage=usage)
    try:
        choice = payload["choices"][0]
        message = choice.get("message") or {}
    except (KeyError, IndexError, TypeError, AttributeError):
        return Result("invalid", error_code="no_choice", usage=usage)
    if message.get("refusal") or choice.get("finish_reason") == "content_filter":
        return Result("refusal", usage=usage)
    try:
        data = json.loads(_strip_fences(message.get("content") or ""))
    except (json.JSONDecodeError, TypeError):
        return Result("invalid", error_code="not_json", usage=usage)
    if not isinstance(data, dict):
        return Result("invalid", error_code="not_object", usage=usage)
    return Result("ok", data=data, usage=usage)


async def call_json(settings: Settings, body: dict[str, Any]) -> Result:
    """Один структурный вызов шлюза ключом EDS. Сеть недоступна — `error`, исключений нет."""
    url = f"{settings.litellm_base_url.rstrip('/')}{CHAT_PATH}"
    headers = {"Authorization": f"Bearer {settings.litellm_api_key.get_secret_value()}"}
    try:
        async with httpx.AsyncClient(transport=TRANSPORT, timeout=settings.ai_timeout_s) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("ai.gateway_unavailable", error=type(exc).__name__)
        return Result("error", error_code="unavailable")
    return interpret(response)
