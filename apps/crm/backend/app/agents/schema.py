"""JSON Schema для structured output из pydantic-модели.

Строгий режим провайдеров требует: все поля в `required`, запрет лишних полей,
без `default` и числовых/строковых ограничений. Ограничения проверяет pydantic
после ответа модели.
"""

import copy
from typing import Any

from pydantic import BaseModel

_DROP = (
    "default",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "title",
)


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = copy.deepcopy(model.model_json_schema())
    _walk(schema)
    return schema


def response_format(model: type[BaseModel], name: str) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": strict_schema(model)},
    }


def _walk(node: Any) -> None:
    """Обходит схему; ключи словарей `properties`/`$defs` — имена, а не ключевые слова."""
    if isinstance(node, list):
        for item in node:
            _walk(item)
        return
    if not isinstance(node, dict):
        return
    for key in _DROP:
        node.pop(key, None)
    if node.get("type") == "object" and "properties" in node:
        node["required"] = list(node["properties"])
        node["additionalProperties"] = False
    for key, value in node.items():
        if key in ("properties", "$defs") and isinstance(value, dict):
            for child in value.values():
                _walk(child)
        else:
            _walk(value)
