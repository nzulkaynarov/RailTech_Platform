"""Integration exception handling (CONTRACTS §0, §2, M3-ERP-01).

Гарантирует единый формат ошибок ERP строго `{"detail": "<CODE>"}` без лишних полей
(в соответствии с OpenAPI компонентом Error и `additionalProperties: false`).
"""

from __future__ import annotations

from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler


class IntegrationConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "CONFLICT"
    default_code = "conflict"

    def __init__(self, detail="CONFLICT"):
        super().__init__(detail=detail, code=detail)


class IntegrationIdempotencyConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "IDEMPOTENCY_CONFLICT"
    default_code = "idempotency_conflict"

    def __init__(self, detail="IDEMPOTENCY_CONFLICT"):
        super().__init__(detail=detail, code=detail)


class IntegrationValidationError(APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "VALIDATION_ERROR"
    default_code = "validation_error"

    def __init__(self, detail="VALIDATION_ERROR"):
        super().__init__(detail=detail, code=detail)


class IntegrationNotFound(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "NOT_FOUND"
    default_code = "not_found"

    def __init__(self, detail="NOT_FOUND"):
        super().__init__(detail=detail, code=detail)


def integration_exception_handler(exc, context):
    """Кастомный обработчик исключений интеграционного API.

    Преобразует любые ошибки DRF и Django к строгому формату `{"detail": "<CODE>"}`.
    Все ошибки валидации сериализаторов возвращаются со статусом 422 и кодом VALIDATION_ERROR.
    """
    response = drf_exception_handler(exc, context)

    if response is None:
        return None

    # Ошибки аутентификации
    if isinstance(exc, (exceptions.AuthenticationFailed, exceptions.NotAuthenticated)):
        response.status_code = status.HTTP_401_UNAUTHORIZED
        response.data = {"detail": "UNAUTHORIZED"}
        return response

    if isinstance(exc, exceptions.PermissionDenied):
        response.status_code = status.HTTP_403_FORBIDDEN
        response.data = {"detail": "FORBIDDEN"}
        return response

    if isinstance(exc, (exceptions.NotFound, Http404, IntegrationNotFound)):
        response.status_code = status.HTTP_404_NOT_FOUND
        response.data = {"detail": "NOT_FOUND"}
        return response

    # Ошибки валидации данных DRF
    if isinstance(exc, (exceptions.ValidationError, IntegrationValidationError)):
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        detail_msg = "VALIDATION_ERROR"
        if isinstance(exc.detail, dict):
            # Проверяем, есть ли явный код ошибки
            first_err = next(iter(exc.detail.values()), None)
            if isinstance(first_err, list) and first_err and hasattr(first_err[0], "code"):
                code_str = str(first_err[0])
                if code_str.isupper():
                    detail_msg = code_str
        elif isinstance(exc.detail, str) and exc.detail.isupper():
            detail_msg = exc.detail
        response.data = {"detail": detail_msg}
        return response

    # Кастомные APIException со строковым кодом (например IDEMPOTENCY_CONFLICT)
    if hasattr(exc, "detail") and isinstance(exc.detail, str):
        response.data = {"detail": exc.detail}
        return response

    data = response.data
    if isinstance(data, dict):
        if "detail" in data:
            val = str(data["detail"])
            if response.status_code == 401:
                response.data = {"detail": "UNAUTHORIZED"}
            elif response.status_code == 404:
                response.data = {"detail": "NOT_FOUND"}
            elif response.status_code == 403:
                response.data = {"detail": "FORBIDDEN"}
            else:
                response.data = {"detail": val if val.isupper() else "ERROR"}
        else:
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            response.data = {"detail": "VALIDATION_ERROR"}
    elif isinstance(data, list):
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        response.data = {"detail": "VALIDATION_ERROR"}

    return response
