"""Portal exception handling: гарантирует формат {"detail": "<CODE>"} по CONTRACTS §4 и Q-17."""

from rest_framework import exceptions, status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler


class PortalConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "CONFLICT"
    default_code = "conflict"

    def __init__(self, detail="CONFLICT"):
        super().__init__(detail=detail, code=detail)


class PortalGone(APIException):
    status_code = status.HTTP_410_GONE
    default_detail = "GONE"
    default_code = "gone"

    def __init__(self, detail="GONE"):
        super().__init__(detail=detail, code=detail)


class PortalValidationError(APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "VALIDATION_ERROR"
    default_code = "validation_error"

    def __init__(self, detail="VALIDATION_ERROR"):
        super().__init__(detail=detail, code=detail)


def portal_exception_handler(exc, context):
    """Кастомный обработчик ошибок для портального API.

    Гарантирует, что каждый ответ об ошибке содержит поле {"detail": "<CODE>"}.
    """
    response = drf_exception_handler(exc, context)

    if response is None:
        return None

    if isinstance(exc, (exceptions.AuthenticationFailed, exceptions.NotAuthenticated)):
        response.status_code = status.HTTP_401_UNAUTHORIZED

    data = response.data
    if isinstance(data, dict):
        if "detail" in data:
            detail_val = data["detail"]
            if hasattr(detail_val, "code") and detail_val.code in (
                "not_authenticated",
                "authentication_failed",
            ):
                response.status_code = status.HTTP_401_UNAUTHORIZED
                if str(detail_val) in ("INVALID_INIT_DATA", "UNAUTHORIZED"):
                    response.data = {"detail": str(detail_val)}
                else:
                    response.data = {"detail": "UNAUTHORIZED"}
            elif hasattr(detail_val, "code") and detail_val.code == "permission_denied":
                response.status_code = status.HTTP_403_FORBIDDEN
                response.data = {"detail": str(detail_val) if str(detail_val) != "FORBIDDEN" else "FORBIDDEN"}
            elif response.status_code == 404:
                response.data = {"detail": "NOT_FOUND"}
            elif response.status_code == 403:
                response.data = {"detail": "FORBIDDEN"}
            elif response.status_code == 401:
                response.data = {
                    "detail": (
                        str(detail_val) if str(detail_val) in ("INVALID_INIT_DATA", "UNAUTHORIZED") else "UNAUTHORIZED"
                    )
                }
            else:
                response.data = {"detail": str(detail_val)}
        else:
            # Словарь ошибок валидации полей
            first_val = next(iter(data.values()), None)
            code = "VALIDATION_ERROR"
            if isinstance(first_val, list) and first_val and hasattr(first_val[0], "code"):
                code = str(first_val[0])
            response.data = {"detail": code if code.isupper() else "VALIDATION_ERROR", "errors": data}
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(data, list):
        response.data = {"detail": "VALIDATION_ERROR", "errors": data}
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

    return response
