"""Опора сторожа «OpenAPI `/api/v1` = поведение кода» (D2-0, B-011).

Схема берётся не из файла, а из кода на каждом прогоне: `core.openapi.build_v1_schema()` (drf-spectacular со всеми
хуками). Файл `packages/contracts/openapi/erp-internal.yaml` — её срез, а совпадение файла с кодом держит
`make -C apps/erp openapi-check`; поэтому тест сверяет ЖИВОЙ ответ с тем, что обещает код, и не зависит от того,
успел ли разработчик перегенерировать файл.

Проверки (`check_response` из `openapi_contract.py` общие с сторожами портала и integration):
  * код ответа описан в операции (недокументированный статус — расхождение);
  * тело подходит под схему ответа: типы, `required`, `nullable`, перечисления, лишние ключи (`extra_keys`);
  * поля тела запроса, которые отправляет клиент (BFF), есть в схеме запроса операции.

OpenAPI 3.0 отличается от JSON Schema только `nullable`; он переводится в `anyOf [..., {"type": "null"}]`.
"""

from __future__ import annotations

from functools import lru_cache

from core.openapi import build_v1_schema
from core.tests.openapi_contract import check_response, deref

JSON = "application/json"


def _to_jsonschema(node):
    """OpenAPI 3.0 → JSON Schema: `nullable: true` становится вариантом `null`."""
    if isinstance(node, list):
        return [_to_jsonschema(item) for item in node]
    if not isinstance(node, dict):
        return node
    converted = {key: _to_jsonschema(value) for key, value in node.items() if key != "nullable"}
    if converted.get("format") == "uri":
        # `URLField(blank=True)` отдаёт "" для read-only поля (`logo_url` настроек): drf-spectacular для read-only не
        # добавляет вариант «пустая строка». Адресность значения тут не проверяется — только тип.
        del converted["format"]
    if "oneOf" in converted:
        # drf-spectacular пишет «значение или пустая строка» как oneOf; пустая строка подходит обеим ветвям
        # (`website`: maxLength 255 и maxLength 0) — для JSON Schema это anyOf.
        converted["anyOf"] = converted.pop("oneOf")
    if node.get("nullable") is True:
        return {"anyOf": [converted, {"type": "null"}]}
    return converted


@lru_cache(maxsize=1)
def contract() -> dict:
    schema, problems = build_v1_schema()
    assert not problems, f"выгрузка /api/v1 с предупреждениями drf-spectacular: {problems}"
    return _to_jsonschema(schema)


def operation(template: str, method: str) -> dict:
    paths = contract()["paths"]
    assert template in paths, f"пути {template} нет в выгрузке /api/v1"
    item = paths[template]
    assert method.lower() in item, f"{method.upper()} {template}: метода нет в выгрузке (есть: {sorted(item)})"
    return item[method.lower()]


def response_errors(response, template: str, method: str) -> list[str]:
    """Нарушения ответа `response` (DRF `Response` тестового клиента) относительно операции."""
    op = operation(template, method)
    status = str(response.status_code)
    if status not in op["responses"]:
        return [f"статус {status} не описан в операции (описаны: {sorted(op['responses'])})"]
    described = op["responses"][status]
    if "$ref" in described:  # общий ответ (`components.responses`)
        described = contract()["components"]["responses"][described["$ref"].rsplit("/", 1)[1]]
    content = described.get("content")
    if not content:
        body = getattr(response, "content", b"")
        return [f"статус {status}: тело ответа не описано, а ответ его отдал ({body[:80]!r})"] if body else []
    media = JSON if JSON in content else next(iter(content))
    if media != JSON:
        return []  # не JSON (HTML, PDF, файл) — тело здесь не проверяется
    schema = deref(content[JSON]["schema"], contract())
    return check_response(response.json(), schema)


def request_properties(template: str, method: str) -> set[str]:
    """Имена полей тела запроса операции (JSON); пусто — тело не описано."""
    op = operation(template, method)
    body = op.get("requestBody", {}).get("content", {})
    media = JSON if JSON in body else next(iter(body), None)
    if media is None:
        return set()
    schema = deref(body[media]["schema"], contract())
    names: set[str] = set()

    def collect(node):
        if not isinstance(node, dict):
            return
        names.update(node.get("properties", {}))
        for key in ("allOf", "anyOf", "oneOf"):
            for part in node.get(key, []):
                collect(part)

    collect(schema)
    return names


def request_fields_missing(template: str, method: str, body: dict) -> list[str]:
    """Поля `body`, которых нет в схеме запроса операции: клиент шлёт то, что контракт не описывает."""
    known = request_properties(template, method)
    return sorted(key for key in body if key not in known)
