"""Единственный клиент ERP к моделям — LiteLLM Proxy по алиасам (ADR-0005, M1-ERP-06).

Прямого SDK провайдера в ERP нет: шлюз говорит на OpenAI-совместимом HTTP API
(`POST {LITELLM_BASE_URL}/v1/chat/completions`), клиент — `httpx` (по рекомендации, DECISIONS
2026-10-14: тонкий синхронный вызов из Celery, полный контроль тела `metadata` и заголовка
стоимости, без второй SDK-обёртки). Что стоит за алиасом — решает LiteLLM (консоль «Модели ИИ»
CRM), код знает только четыре алиаса ERP.

Каждый вызов несёт `metadata`:
- `tags` = `system=erp`, `feature=<функция>`, `model=<алиас>` — журнал расходов LiteLLM, по нему
  строится страница «Расходы» консоли CRM (ARCHITECTURE §8);
- `trace_name`, `generation_name`, `trace_id`/`session_id` (= id задачи), `trace_user_id`
  (= сотрудник), `trace_metadata` (версия промпта) — трейс Langfuse пишет сам шлюз колбэком
  ключа ERP (`ai_gateway_sync`); ERP с Langfuse напрямую не говорит.

Структурный вывод — `response_format: json_schema` (LiteLLM переводит в structured output
провайдера). Ошибки — логируемый no-op: `JsonResult` со статусом, сервис возвращает нейтральный
результат и никогда не роняет задачу. Исключение одно — исчерпанный бюджет (`AIBudgetExceeded`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

import httpx
from django.conf import settings

from core.external_status import is_enabled

from .budget import assert_budget_available
from .context import current_trace
from .errors import AI_BAD_RESPONSE, AI_GATEWAY_ERROR, AI_GATEWAY_UNAVAILABLE, AIBudgetExceeded
from .ledger import CallRecord, CallUsage, record_call
from .prompts import Prompt

logger = logging.getLogger(__name__)

INTAKE_MODEL = "intake-model"
MATCH_MODEL = "match-model"
DRAFT_MODEL = "draft-model"
ENRICH_MODEL = "enrich-model"

#: Функция → алиас (DECISIONS 2026-10-14, по рекомендации). Новая функция без строки здесь не
#: позовёт модель: `alias_for` бросит KeyError — ошибка кода, а не тихий выбор модели.
FEATURE_ALIASES: dict[str, str] = {
    "intake": INTAKE_MODEL,  # файл клиента (Excel/CSV/PDF/фото) → строки запроса
    "compose": INTAKE_MODEL,  # свободный текст → строки запроса
    "preflight": INTAKE_MODEL,  # советы по качеству строк запроса
    "extract": INTAKE_MODEL,  # договор/встречный счёт → денежные поля
    "match": MATCH_MODEL,  # строки запроса → позиции каталога (и черновик КП)
    "canonicalize": MATCH_MODEL,  # нормализация наименований для поиска
    "hs": MATCH_MODEL,  # подбор кода ТН ВЭД из кандидатов справочника
    "diff": DRAFT_MODEL,  # КП против запроса: смысловые расхождения
    "enrich": ENRICH_MODEL,  # черновик карточки товара/услуги
    "price_list": ENRICH_MODEL,  # прайс-лист поставщика → строки каталога
}

COST_HEADER = "x-litellm-response-cost"
SYSTEM_TAG = "system=erp"
CHAT_PATH = "/v1/chat/completions"
_RETRY_BACKOFF_S = 2.0


def alias_for(feature: str) -> str:
    return FEATURE_ALIASES[feature]


@dataclass(frozen=True)
class JsonCall:
    """Один структурный вызов: системный промпт из файла + данные пользователя отдельным блоком."""

    feature: str
    prompt: Prompt
    system: str
    user_content: list[dict]
    schema: dict
    max_tokens: int
    retries: int = 0
    mask_input: bool = False


@dataclass(frozen=True)
class JsonResult:
    status: str  # ok | refusal | truncated | invalid_json | error | disabled
    data: dict | None = None
    error_code: str = ""
    usage: CallUsage = field(default_factory=CallUsage)

    @property
    def ok(self) -> bool:
        return self.status == "ok" and isinstance(self.data, dict)


class TransportResponse(NamedTuple):
    status_code: int
    headers: dict[str, str]
    payload: dict | None


def http_transport(url: str, body: dict, headers: dict[str, str], timeout: float) -> TransportResponse:
    """HTTP-вызов шлюза — единственная точка сети модуля."""
    response = httpx.post(url, json=body, headers=headers, timeout=timeout)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return TransportResponse(response.status_code, {k.lower(): v for k, v in response.headers.items()}, payload)


#: Транспорт, через который идут вызовы. Тесты подменяют его фейком (`ai.testing.FakeGateway`),
#: корневой conftest — блокировкой; evals возвращают `http_transport`.
_transport = http_transport


def trace_id_for(session_id: str) -> str:
    """Один трейс Langfuse на задачу: 32 hex из UUID задачи или из хэша иного идентификатора."""
    try:
        return uuid.UUID(session_id).hex
    except ValueError:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]


def _metadata(call: JsonCall, alias: str) -> dict:
    trace = current_trace()
    session_id = trace.session_id if trace else "adhoc"
    job_feature = (trace.job_feature if trace else "") or call.feature
    metadata = {
        "tags": [SYSTEM_TAG, f"feature={call.feature}", f"model={alias}"],
        "trace_name": f"erp.{job_feature}",
        "generation_name": f"erp.{call.feature}",
        "trace_id": trace_id_for(session_id),
        "session_id": session_id,
        "trace_metadata": {
            "system": "erp",
            "job_feature": job_feature,
            "prompt": call.prompt.name,
            "prompt_version": call.prompt.version,
        },
    }
    if trace and trace.user_id:
        metadata["trace_user_id"] = f"erp-staff-{trace.user_id}"
    if call.mask_input:
        # Файлы клиента (base64) и денежные документы не копируются в Langfuse: трейс хранит
        # метаданные, токены и ответ, а не сам документ.
        metadata["mask_input"] = True
    return metadata


def build_body(call: JsonCall) -> dict:
    alias = alias_for(call.feature)
    return {
        "model": alias,
        "messages": [
            {"role": "system", "content": call.system},
            {"role": "user", "content": call.user_content},
        ],
        "max_tokens": call.max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": call.prompt.name, "schema": call.schema, "strict": True},
        },
        "metadata": _metadata(call, alias),
    }


def _send(body: dict, retries: int) -> TransportResponse | None:
    """POST с повторами только на сеть/5xx. None — шлюз недоступен после всех попыток."""
    url = f"{settings.LITELLM_BASE_URL}{CHAT_PATH}"
    headers = {"Authorization": f"Bearer {settings.LITELLM_API_KEY}"}
    for attempt in range(retries + 1):
        try:
            response = _transport(url, body, headers, settings.AI_REQUEST_TIMEOUT)
        except httpx.HTTPError as exc:
            logger.warning("AI gateway transport error (attempt %s/%s): %s", attempt + 1, retries + 1, exc)
            response = None
        if response is not None and response.status_code < 500:
            return response
        if attempt < retries:
            time.sleep(_RETRY_BACKOFF_S * (2**attempt))
    return response


def _parse_cost(raw: str | None) -> Decimal | None:
    try:
        return Decimal(raw) if raw else None
    except (InvalidOperation, ValueError):
        return None


def _usage(response: TransportResponse | None, latency_ms: int) -> CallUsage:
    if response is None:
        return CallUsage(latency_ms=latency_ms)
    usage = (response.payload or {}).get("usage") or {}
    return CallUsage(
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        cost_usd=_parse_cost(response.headers.get(COST_HEADER)),
        latency_ms=latency_ms,
    )


def _is_budget_error(response: TransportResponse) -> bool:
    error = (response.payload or {}).get("error") or {}
    return isinstance(error, dict) and str(error.get("type") or "").lower() == "budget_exceeded"


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()


def _interpret(response: TransportResponse) -> tuple[str, dict | None, str]:
    """Ответ шлюза → (статус, данные, код ошибки). Без исключений."""
    if response.status_code >= 400:
        return "error", None, AI_GATEWAY_ERROR
    try:
        choice = response.payload["choices"][0]
        message = choice.get("message") or {}
    except (KeyError, IndexError, TypeError):
        return "invalid_json", None, AI_BAD_RESPONSE
    finish_reason = str(choice.get("finish_reason") or "")
    if message.get("refusal") or finish_reason == "content_filter":
        return "refusal", None, ""
    try:
        data = json.loads(_strip_fences(message.get("content") or ""))
    except (json.JSONDecodeError, TypeError):
        status = "truncated" if finish_reason == "length" else "invalid_json"
        return status, None, AI_BAD_RESPONSE
    if not isinstance(data, dict):
        return "invalid_json", None, AI_BAD_RESPONSE
    return "ok", data, ""


def _record(call: JsonCall, status: str, error_code: str, usage: CallUsage) -> None:
    trace = current_trace()
    if trace is not None:
        trace.add_call(prompt=call.prompt.name, version=call.prompt.version, usage=usage, error_code=error_code)
    record_call(
        CallRecord(
            session_id=trace.session_id if trace else "adhoc",
            user_id=trace.user_id if trace else None,
            feature=call.feature,
            alias=alias_for(call.feature),
            prompt_name=call.prompt.name,
            prompt_version=call.prompt.version,
            status=status,
            error_code=error_code,
            usage=usage,
        )
    )


def call_json(call: JsonCall) -> JsonResult:
    """Структурный вызов модели через шлюз. Никогда не бросает, кроме ``AIBudgetExceeded``."""
    if not getattr(settings, "AI_IMPORT_ENABLED", False):
        return JsonResult(status="disabled", error_code=AI_GATEWAY_UNAVAILABLE)
    if not is_enabled("litellm"):  # выключатель из CRM (M3-ERP-06): вызова нет, ни платного, ни в журнале
        return JsonResult(status="disabled", error_code=AI_GATEWAY_UNAVAILABLE)
    assert_budget_available()
    body = build_body(call)
    started = time.monotonic()
    response = _send(body, call.retries)
    usage = _usage(response, int((time.monotonic() - started) * 1000))
    if response is None:
        status, data, error_code = "error", None, AI_GATEWAY_UNAVAILABLE
    elif _is_budget_error(response):
        _record(call, "budget", AIBudgetExceeded.code, usage)
        raise AIBudgetExceeded("litellm-key")
    else:
        status, data, error_code = _interpret(response)
    _record(call, status, error_code, usage)
    _log_outcome(call, status, response, usage)
    return JsonResult(status=status, data=data, error_code=error_code, usage=usage)


def _log_outcome(call: JsonCall, status: str, response: TransportResponse | None, usage: CallUsage) -> None:
    if status == "ok":
        logger.info(
            "AI %s ok: model=%s in=%s out=%s cost=%s prompt=%s@%s",
            call.feature,
            alias_for(call.feature),
            usage.input_tokens,
            usage.output_tokens,
            usage.cost_usd,
            call.prompt.name,
            call.prompt.version,
        )
        return
    code = response.status_code if response is not None else "no-response"
    detail = ((response.payload or {}).get("error") if response is not None else None) or ""
    logger.warning("AI %s %s (http=%s): %s", call.feature, status, code, str(detail)[:300])


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}
