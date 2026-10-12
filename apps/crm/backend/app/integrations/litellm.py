"""LiteLLM Proxy — единственный шлюз к моделям (SPEC §1.6, ADR-0004).

Код обращается только к алиасам (`dialog-model`, `qualifier-model`, `judge-model`,
`embed-model`, `fallback-model`); конкретные модели — в `infra/litellm.config.yaml`.
Клиент — OpenAI-совместимый (LiteLLM Proxy реализует этот API).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

import httpx
from openai import AsyncOpenAI
from pydantic import AnyHttpUrl

from app.config import Settings
from app.domain.embedding_profile import ACTIVE_PROFILE, EmbeddingProfile, l2_normalize
from app.integrations.llm_usage import Purpose, UsageEvent, UsageSink, parse_cost

Alias = Literal["dialog-model", "qualifier-model", "judge-model", "fallback-model"]
EMBED_ALIAS: Final = "embed-model"
EMBED_BATCH: Final = 64
COST_HEADER: Final = "x-litellm-response-cost"


async def ping(client: httpx.AsyncClient, base_url: AnyHttpUrl) -> None:
    """Liveness прокси. Доступность конкретных моделей здесь не проверяется."""
    response = await client.get(f"{str(base_url).rstrip('/')}/health/liveliness")
    response.raise_for_status()


@dataclass(frozen=True, slots=True)
class Usage:
    model: str
    tokens_in: int
    tokens_out: int


def make_client(settings: Settings, timeout_s: float | None = None) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.litellm_api_key.get_secret_value() or "unset",
        base_url=f"{str(settings.litellm_base_url).rstrip('/')}/v1",
        timeout=timeout_s or settings.llm_timeout_s,
        max_retries=1,
    )


class Embedder:
    """Embeddings через `embed-model` с префиксами задачи и L2-нормализацией (ADR-0004)."""

    def __init__(
        self,
        client: AsyncOpenAI,
        profile: EmbeddingProfile = ACTIVE_PROFILE,
        usage: UsageSink | None = None,
    ) -> None:
        self._client = client
        self._profile = profile
        self._usage = usage

    @property
    def dimensions(self) -> int:
        return self._profile.dimensions

    async def embed_query(self, text: str) -> list[float]:
        (vector,) = await self._embed([self._profile.format_query(text)], "embed_query")
        return vector

    async def embed_documents(self, texts: Sequence[tuple[str, str | None]]) -> list[list[float]]:
        """`texts` — пары (текст чанка, заголовок документа)."""
        formatted = [self._profile.format_document(text, title) for text, title in texts]
        vectors: list[list[float]] = []
        for start in range(0, len(formatted), EMBED_BATCH):
            batch = formatted[start : start + EMBED_BATCH]
            vectors.extend(await self._embed(batch, "embed_ingest"))
        return vectors

    async def _embed(self, inputs: list[str], purpose: Purpose) -> list[list[float]]:
        raw = await self._client.embeddings.with_raw_response.create(
            model=EMBED_ALIAS, input=inputs, dimensions=self._profile.dimensions
        )
        response = raw.parse()
        if self._usage is not None:
            usage = getattr(response, "usage", None)
            await self._usage.record(
                UsageEvent(
                    purpose=purpose,
                    alias=EMBED_ALIAS,
                    model=getattr(response, "model", None),
                    input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    output_tokens=0,
                    cost_usd=parse_cost(raw.headers.get(COST_HEADER)),
                )
            )
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = [l2_normalize(item.embedding) for item in ordered]
        if any(len(v) != self._profile.dimensions for v in vectors):
            raise ValueError("embedding dimension mismatch with the active profile")
        return vectors
