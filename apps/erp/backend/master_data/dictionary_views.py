"""`/api/v1/dictionaries` ERP — общий ресурс справочников (правила — `master_data/dictionaries.py`).

Читает любой сотрудник своей компании, меняет держатель `settings.edit` (как прежние вьюсеты справочников).
Ошибки — в виде EDS и CRM: `{code, message, details}`; BFF переводит их так же.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import HasRolePermission, RoleGatedViewMixin

from . import dictionaries as svc

_TAGS = ["Master Data"]


def _error(exc: svc.DictionaryError) -> Response:
    return Response({"code": exc.code, "message": exc.message, "details": exc.details}, status=exc.status)


class _Base(RoleGatedViewMixin, APIView):
    """Чтение — сотрудник, запись — `settings.edit` (через `HasRolePermission`)."""

    required_permissions = {
        "POST": "settings.edit",
        "PATCH": "settings.edit",
        "PUT": "settings.edit",
        "DELETE": "settings.edit",
    }

    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), HasRolePermission()]


class DictionaryCatalogView(_Base):
    @extend_schema(
        operation_id="listDictionaries",
        summary="Dictionaries catalog",
        responses={200: OpenApiTypes.OBJECT},
        tags=_TAGS,
    )
    def get(self, request):
        return Response(svc.catalog())


class DictionaryItemsView(_Base):
    @extend_schema(
        operation_id="listDictionaryItems",
        summary="Dictionary values",
        parameters=[OpenApiParameter("include_hidden", bool, OpenApiParameter.QUERY)],
        responses={200: OpenApiTypes.OBJECT},
        tags=_TAGS,
    )
    def get(self, request, kind):
        hidden = str(request.query_params.get("include_hidden", "")).lower() in ("1", "true")
        try:
            return Response(svc.items(kind, include_hidden=hidden))
        except svc.DictionaryError as exc:
            return _error(exc)

    @extend_schema(
        operation_id="createDictionaryItem",
        summary="Add a dictionary value",
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
        tags=_TAGS,
    )
    def post(self, request, kind):
        try:
            return Response(svc.create(kind, dict(request.data)), status=status.HTTP_201_CREATED)
        except svc.DictionaryError as exc:
            return _error(exc)


class DictionaryOrderView(_Base):
    @extend_schema(
        operation_id="reorderDictionaryItems",
        summary="Reorder dictionary values",
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        tags=_TAGS,
    )
    def put(self, request, kind):
        codes = request.data.get("codes") if isinstance(request.data, dict) else None
        if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
            return _error(
                svc.DictionaryError(422, "VALIDATION_FAILED", "Нужен список кодов.", {"fields": {"codes": "invalid"}})
            )
        try:
            return Response(svc.reorder(kind, codes))
        except svc.DictionaryError as exc:
            return _error(exc)


class DictionaryItemView(_Base):
    @extend_schema(
        operation_id="updateDictionaryItem",
        summary="Change a dictionary value",
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        tags=_TAGS,
    )
    def patch(self, request, kind, code):
        try:
            return Response(svc.update(kind, code, dict(request.data)))
        except svc.DictionaryError as exc:
            return _error(exc)

    @extend_schema(
        operation_id="deleteDictionaryItem", summary="Delete a dictionary value", responses={204: None}, tags=_TAGS
    )
    def delete(self, request, kind, code):
        try:
            svc.delete(kind, code)
        except svc.DictionaryError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)
