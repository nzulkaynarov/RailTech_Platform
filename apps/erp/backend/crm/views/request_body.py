"""Разбор тела запроса аварийных экшенов: JSON-объект, а не массив или строка."""

from rest_framework import status
from rest_framework.response import Response


def invalid_body_response():
    return Response({"detail": "INVALID_REQUEST_BODY"}, status=status.HTTP_400_BAD_REQUEST)


def is_object_body(request) -> bool:
    """`request.data` — словарь/QueryDict; тело-массив (`[]`) иначе падает на `.get` → 500."""
    return hasattr(request.data, "get")
