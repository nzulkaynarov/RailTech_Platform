"""D2-0 (B-011): выгрузка OpenAPI `/api/v1` строится без предупреждений и ошибок drf-spectacular.

Каждое предупреждение — место, где схема угадана или потеряна («unable to guess serializer», «component name
collision», «could not derive type of path parameter» …), то есть расхождение описания с кодом. Тот же страж стоит в
`make -C apps/erp openapi` / `openapi-check` (`manage.py openapi_v1_check`); тест повторяет его в `make check-erp`.
Граница проверки — `/api/v1/` (портал и integration описаны руками и сверяются своими сторожами): `core/openapi.py`.
"""

from functools import lru_cache

from core.openapi import STANDARD_RESPONSES, build_v1_schema

build_v1_schema = lru_cache(maxsize=1)(build_v1_schema)  # выгрузка дорогая: одна на три теста


def test_v1_schema_has_no_spectacular_warnings():
    schema, problems = build_v1_schema()
    assert not problems, "drf-spectacular: " + "; ".join(sorted(problems))
    assert schema["paths"], "в выгрузке нет ни одного пути /api/v1/"
    assert all(path.startswith("/api/v1/") for path in schema["paths"])


def test_every_error_response_has_a_body_schema():
    """Нет ответа 4xx/5xx без схемы тела: либо общий `ErrorDetail`/`BadRequest`, либо схема операции."""
    schema, _ = build_v1_schema()
    shared = schema["components"]["responses"]
    bare = []
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            for code, response in operation.get("responses", {}).items():
                if not str(code).startswith(("4", "5")):
                    continue
                if "$ref" in response:
                    response = shared[response["$ref"].rsplit("/", 1)[1]]
                if not response.get("content"):
                    bare.append(f"{method.upper()} {path} {code}")
    assert not bare, f"ответы об ошибке без схемы тела ({len(bare)}): {bare[:10]}"


def test_standard_responses_are_declared_for_secured_operations():
    schema, _ = build_v1_schema()
    operation = schema["paths"]["/api/v1/accounts/companies/{id}/settings/"]["patch"]
    for code in ("400", "401", "403", "404"):
        assert code in operation["responses"], code
    assert set(schema["components"]["responses"]) >= {component for component, _d, _s in STANDARD_RESPONSES.values()}
