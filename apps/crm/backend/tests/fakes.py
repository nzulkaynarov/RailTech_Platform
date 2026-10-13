"""Детерминированные подмены внешних сервисов для тестов (без сети и ключей)."""

import hashlib
import math
import re
from collections.abc import Sequence

from app.domain.embedding_profile import l2_normalize

DIM = 1536
_WORD = re.compile(r"\w+", re.UNICODE)


def hash_embedding(text: str, dim: int = DIM) -> list[float]:
    """Мешок слов → вектор: тексты с общими словами близки по косинусу."""
    vector = [0.0] * dim
    for word in _WORD.findall(text.casefold()):
        digest = hashlib.sha256(word.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        vector[index] += 1.0 + (digest[4] / 255) * 0.01
    if not any(vector):
        vector[0] = 1.0
    return l2_normalize(vector)


class FakeEmbedder:
    dimensions = DIM

    async def embed_query(self, text: str) -> list[float]:
        return hash_embedding(text)

    async def embed_documents(self, texts: Sequence[tuple[str, str | None]]) -> list[list[float]]:
        return [hash_embedding(f"{title or ''} {text}") for text, title in texts]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return math.fsum(x * y for x, y in zip(a, b, strict=True))
