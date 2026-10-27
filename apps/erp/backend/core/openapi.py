"""Выгрузка OpenAPI `/api/v1` (drf-spectacular): общий компонент ошибки и страж «без предупреждений» (D2-0, B-011).

`erp-internal.yaml` — срез этой выгрузки (`scripts/export_internal_contract.py`), поэтому описание обязано быть правдой
о коде: каждая операция имеет явные схемы запроса и ответа, а генератор молчит. Предупреждение drf-spectacular
(«unable to guess serializer», «component name collision», «could not resolve …») — это место, где схема угадана или
потеряна, то есть расхождение с кодом. `check_v1_schema()` строит выгрузку только по `/api/v1/` и возвращает все
предупреждения и ошибки генератора; `manage.py openapi_v1_check` (шаг `make -C apps/erp openapi` и `openapi-check`) и
тест `core/tests/test_openapi_v1_clean.py` падают, если список не пуст.

Почему только `/api/v1/`: портал (`/api/portal/v1/`) и integration (`/api/integration/…`) описаны руками
(`erp-portal.yaml`, `erp-integration.yaml`) и сверяются сторожами в своих тестах; генерируемое описание этих путей в
`schema.json` не вход ни для одного контракта, а его шум (пути со слэшем и без, представления без сериализатора)
маскировал бы настоящие сигналы.

Ошибки. Тела отказов ERP — `{"detail": "КОД"}` (CONVENTIONS ERP §5; код — `UPPER_SNAKE`, у DRF-ошибок авторизации —
английская фраза) либо словарь ошибок полей `{"поле": ["текст"]}` от сериализатора. Для ответов 4xx/5xx, у которых
в коде нет явной схемы (`OpenApiResponse(description=…)`), `describe_error_responses` подставляет общий компонент
`ErrorDetail` (для 400 — `BadRequest` = `ErrorDetail` или `ValidationErrors`): описание ошибок едино в
каждой операции, а коды остаются в `description`. Особые формы (`missing_blocks`) задаются в самой операции.
"""

from __future__ import annotations

from drf_spectacular.openapi import AutoSchema
from rest_framework import serializers
from rest_framework.fields import empty

V1_PREFIX = "/api/v1/"

ERROR_DETAIL = "ErrorDetail"
VALIDATION_ERRORS = "ValidationErrors"
BAD_REQUEST = "BadRequest"


def only_v1_endpoints(endpoints, **kwargs):
    """PREPROCESSING_HOOK строгой выгрузки: оставить пути `/api/v1/`."""
    return [endpoint for endpoint in endpoints if endpoint[0].startswith(V1_PREFIX)]


def _components(result) -> dict:
    return result.setdefault("components", {}).setdefault("schemas", {})


def _ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def _requires_auth(operation) -> bool:
    security = operation.get("security")
    return bool(security) and all(requirement for requirement in security)


#: Типовые отказы DRF как общие ответы (`components.responses`): операция ссылается на них одной строкой.
STANDARD_RESPONSES = {
    "400": ("BadRequestResponse", "Отказ проверки: код `detail` или ошибки полей сериализатора", BAD_REQUEST),
    "401": ("UnauthorizedResponse", "Нет действительной сессии (токена доступа)", ERROR_DETAIL),
    "403": ("ForbiddenResponse", "Нет права на операцию (код права в `detail`)", ERROR_DETAIL),
    "404": ("NotFoundResponse", "Объекта нет или он чужой (другая компания)", ERROR_DETAIL),
}


def _standard_errors(path: str, operation: dict) -> list[str]:
    """Коды отказов, возможные у операции всегда, даже если вьюха их не называет (DRF сам их отдаёт)."""
    codes = []
    if "requestBody" in operation:
        codes.append("400")
    if _requires_auth(operation):
        codes += ["401", "403"]
    if "{" in path:
        codes.append("404")
    return codes


def describe_error_responses(result, generator=None, request=None, public=None):
    """POSTPROCESSING_HOOK: ответы 4xx/5xx `/api/v1/` описаны единым компонентом ошибки.

    Что делает для каждой операции:
      * добавляет отказы, которые DRF отдаёт всегда (400 при теле запроса, 401/403 при авторизации, 404 при
        `{id}` в пути), если вьюха их не назвала, — ссылкой на общий ответ (`components.responses`);
      * ответам 4xx/5xx без схемы (`OpenApiResponse(description=…)`) подставляет `ErrorDetail`, а для 400 —
        `BadRequest` (`ErrorDetail` или `ValidationErrors`). Коды ошибок остаются в `description`.
    Ответы с явной схемой (например, `missing_blocks`) не трогаются.
    """
    used: set[str] = set()
    shared: set[str] = set()
    for path, item in result.get("paths", {}).items():
        if not path.startswith(V1_PREFIX):
            continue
        for operation in item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            responses = operation["responses"]
            for code in _standard_errors(path, operation):
                if code not in responses:
                    component, _description, schema_name = STANDARD_RESPONSES[code]
                    responses[code] = {"$ref": f"#/components/responses/{component}"}
                    shared.add(code)
                    used.add(schema_name)
            for code, response in responses.items():
                if not (str(code).startswith(("4", "5")) and isinstance(response, dict)):
                    continue
                if "content" in response or "$ref" in response:
                    continue
                name = BAD_REQUEST if str(code) == "400" else ERROR_DETAIL
                used.add(name)
                response["content"] = {"application/json": {"schema": _ref(name)}}
    if not used:
        return result
    schemas = _components(result)
    schemas[ERROR_DETAIL] = {
        "type": "object",
        "description": (
            "Отказ ERP: `detail` — код ошибки (`UPPER_SNAKE`, например `REASON_REQUIRED`; допустимые коды операции "
            "перечислены в описании ответа) или английская фраза DRF для ошибок авторизации и лимитов. "
            "`message` — текст для человека, если ERP его присылает."
        ),
        "properties": {
            "detail": {"type": "string", "description": "Код ошибки или фраза DRF"},
            "message": {"type": "string", "description": "Текст для человека (не у всех ошибок)"},
        },
        "required": ["detail"],
    }
    if BAD_REQUEST in used:
        schemas[VALIDATION_ERRORS] = {
            "type": "object",
            "description": (
                "Ошибки полей от сериализатора DRF: ключ — имя поля (или `non_field_errors`), значение — список "
                "текстов (у вложенных объектов и списков — вложенная структура)."
            ),
            "additionalProperties": {},
        }
        schemas[BAD_REQUEST] = {
            "description": "Отказ проверки: либо код `{detail}`, либо ошибки полей сериализатора.",
            "anyOf": [_ref(ERROR_DETAIL), _ref(VALIDATION_ERRORS)],
        }
    responses_component = result.setdefault("components", {}).setdefault("responses", {})
    for code in sorted(shared):
        component, description, schema_name = STANDARD_RESPONSES[code]
        responses_component[component] = {
            "description": description,
            "content": {"application/json": {"schema": _ref(schema_name)}},
        }
    return result


def build_v1_schema() -> tuple[dict, list[str]]:
    """Выгрузка только `/api/v1/` (со всеми хуками) и предупреждения/ошибки генератора (пусто — выгрузка чистая)."""
    from drf_spectacular.drainage import GENERATOR_STATS
    from drf_spectacular.generators import SchemaGenerator
    from drf_spectacular.settings import patched_settings, spectacular_settings

    hooks = [*spectacular_settings.PREPROCESSING_HOOKS, "core.openapi.only_v1_endpoints"]
    GENERATOR_STATS.reset()
    with GENERATOR_STATS.silence(), patched_settings({"PREPROCESSING_HOOKS": hooks}):
        schema = SchemaGenerator().get_schema(request=None, public=True)
    problems = [*GENERATOR_STATS._error_cache, *GENERATOR_STATS._warn_cache]
    GENERATOR_STATS.reset()
    return schema, problems


def check_v1_schema() -> list[str]:
    """Предупреждения и ошибки генератора для `/api/v1/` (пусто — выгрузка чистая)."""
    return build_v1_schema()[1]


def _relation_may_be_empty(model, attrs) -> bool:
    """Есть ли на пути `attrs` (кроме последнего звена) связь модели, которая бывает пустой."""
    from django.core.exceptions import FieldDoesNotExist

    current = model
    for attr in attrs[:-1]:
        try:
            relation = current._meta.get_field(attr)
        except FieldDoesNotExist:
            return False  # свойство, не поле модели — не гадаем
        if not relation.is_relation:
            return False
        if relation.null or relation.auto_created or relation.many_to_many or relation.one_to_many:
            return True  # nullable FK, обратная связь (может не существовать)
        current = relation.related_model
    return False


def _may_be_absent(serializer, field) -> bool:
    """Поле-проекция `source="связь.атрибут"` через пустую связь модели и без значения по умолчанию.

    `Field.get_attribute` при `AttributeError` (связь пуста) для необязательного поля бросает `SkipField` — ключа в
    ответе нет (не `null`). drf-spectacular же вносит любое `read_only`-поле в `required`, то есть обещает ключ,
    которого код не отдаёт (`role_code` / `role_name` у пользователя без роли). Связь `NOT NULL` ключ не теряет.
    """
    model = getattr(getattr(serializer, "Meta", None), "model", None)
    attrs = getattr(field, "source_attrs", [])
    return (
        model is not None
        and field.read_only
        and field.default is empty
        and not field.allow_null
        and not isinstance(field, serializers.SerializerMethodField)
        and len(attrs) > 1
        and _relation_may_be_empty(model, attrs)
    )


class ErpAutoSchema(AutoSchema):
    """AutoSchema ERP: поля, которые код может не отдать, не попадают в `required` (см. `_may_be_absent`)."""

    def _map_basic_serializer(self, serializer, direction):
        schema = super()._map_basic_serializer(serializer, direction)
        absent = {name for name, field in serializer.fields.items() if _may_be_absent(serializer, field)}
        if absent and "required" in schema:
            schema["required"] = [name for name in schema["required"] if name not in absent]
            if not schema["required"]:
                del schema["required"]
        return schema
