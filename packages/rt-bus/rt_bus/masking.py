"""Секретные поля `data` (CONTRACTS §9.2): код акцепта не оседает в outbox, inbox и журналах.

Издатель пишет в outbox маску, значения кладёт во временное хранилище (`SecretStash`, например кэш Redis с TTL) и
подставляет их в тело доставки; приёмник хранит в inbox маску, а полное событие получают только inline-обработчики
(`@subscribe(..., inline=True)`) во время запроса.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

MASK = "***"

#: Тип события → пути секретных полей в `data` (через точку).
DEFAULT_SECRET_FIELDS: Mapping[str, tuple[str, ...]] = {
    "uz.railtech.erp.quote.acceptance_code_requested.v1": ("payload.code",),
}


def _walk(container: Any, path: str) -> tuple[dict[str, Any], str] | None:
    parts = path.split(".")
    node = container
    for part in parts[:-1]:
        if not isinstance(node, dict) or not isinstance(node.get(part), dict):
            return None
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        return None
    return node, parts[-1]


def mask_data(data: Mapping[str, Any], paths: Sequence[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """(`data` с масками, `{путь: значение}`); нет полей — копия и пустой словарь."""
    masked = copy.deepcopy(dict(data))
    secrets: dict[str, Any] = {}
    for path in paths:
        found = _walk(masked, path)
        if found is None:
            continue
        node, key = found
        secrets[path] = node[key]
        node[key] = MASK
    return masked, secrets


def unmask_data(data: Mapping[str, Any], secrets: Mapping[str, Any]) -> dict[str, Any]:
    restored = copy.deepcopy(dict(data))
    for path, value in secrets.items():
        found = _walk(restored, path)
        if found is not None:
            node, key = found
            node[key] = value
    return restored


def redact(messages: Sequence[str], secrets: Mapping[str, Any]) -> list[str]:
    """Сообщения (ошибки схемы, логи) без значений секретных полей: jsonschema цитирует значение и объект целиком."""
    needles = sorted(
        {s for value in secrets.values() if value not in (None, "") for s in (repr(value), str(value))},
        key=len,
        reverse=True,
    )
    out = []
    for message in messages:
        for needle in needles:
            message = message.replace(needle, MASK)
        out.append(message)
    return out


class SecretStash(Protocol):
    """Временное хранилище секретных значений издателя (синхронное; Django — кэш)."""

    def put(self, event_id: str, values: Mapping[str, Any]) -> None: ...

    def get(self, event_id: str) -> Mapping[str, Any] | None: ...


class AsyncSecretStash(Protocol):
    async def put(self, event_id: str, values: Mapping[str, Any]) -> None: ...

    async def get(self, event_id: str) -> Mapping[str, Any] | None: ...


class MemoryStash:
    """Хранилище в памяти процесса (тесты; один процесс)."""

    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}

    def put(self, event_id: str, values: Mapping[str, Any]) -> None:
        self.values[event_id] = dict(values)

    def get(self, event_id: str) -> Mapping[str, Any] | None:
        return self.values.get(event_id)
