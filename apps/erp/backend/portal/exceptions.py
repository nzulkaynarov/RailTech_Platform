"""Portal exception handling: гарантирует формат {"detail": "<CODE>"} по CONTRACTS §4 и Q-17."""

from portal.error_codes import ERROR_CODES, FALLBACK_BY_STATUS
from rest_framework import exceptions, status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler


class PortalBadRequest(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "VALIDATION_ERROR"
    default_code = "bad_request"

    def __init__(self, detail="VALIDATION_ERROR"):
        super().__init__(detail=detail, code=detail)


class PortalConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "CONFLICT"
    default_code = "conflict"

    def __init__(self, detail="CONFLICT"):
        super().__init__(detail=detail, code=detail)


class PortalGone(APIException):
    status_code = status.HTTP_410_GONE
    default_detail = "MAGIC_LINK_EXPIRED"
    default_code = "gone"

    def __init__(self, detail="MAGIC_LINK_EXPIRED"):
        super().__init__(detail=detail, code=detail)


class PortalTooManyRequests(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "TOO_MANY_REQUESTS"
    default_code = "too_many_requests"

    def __init__(self, detail="TOO_MANY_REQUESTS"):
        super().__init__(detail=detail, code=detail)


class PortalDeliveryFailed(APIException):
    """Письмо не ушло (сбой транспорта): 503 `DELIVERY_FAILED` (контракт 0.3.0, Q-FIX23-2)."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "DELIVERY_FAILED"
    default_code = "delivery_failed"

    def __init__(self, detail="DELIVERY_FAILED"):
        super().__init__(detail=detail, code=detail)


class PortalValidationError(APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "VALIDATION_ERROR"
    default_code = "validation_error"

    def __init__(self, detail="VALIDATION_ERROR"):
        super().__init__(detail=detail, code=detail)


def portal_exception_handler(exc, context):
    """Кастомный обработчик ошибок для портального API.

    Гарантирует, что каждый ответ об ошибке — ровно `{"detail": "<CODE>"}` с кодом из `ErrorCode` контракта
    (схема `Error` запрещает другие ключи; текст ошибок валидации клиенту не нужен — он узнаёт код).
    """
    response = drf_exception_handler(exc, context)

    if response is None:
        return None

    if isinstance(exc, exceptions.Throttled):
        # Лимит частоты (portal/throttles.py): код вместо английской фразы DRF; Retry-After уже выставил DRF.
        response.data = {"detail": "TOO_MANY_REQUESTS"}
        return response

    if isinstance(exc, (exceptions.AuthenticationFailed, exceptions.NotAuthenticated)):
        response.status_code = status.HTTP_401_UNAUTHORIZED
    elif isinstance(exc, exceptions.PermissionDenied):
        response.status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, (exceptions.ParseError, exceptions.ValidationError)):
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

    detail = None
    data = response.data
    if isinstance(data, dict) and "detail" in data:
        detail = str(data["detail"])
    elif isinstance(data, dict) and data:
        # Ошибки валидации полей: первый внутренний код, если он из перечня, иначе общий.
        first = next(iter(data.values()))
        first = first[0] if isinstance(first, list) and first else first
        detail = str(first)
    if detail not in ERROR_CODES:
        detail = FALLBACK_BY_STATUS.get(response.status_code, "VALIDATION_ERROR")
    response.data = {"detail": detail}
    return response
