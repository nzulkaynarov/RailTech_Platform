"""Техдокументация (D2-3): `/api/v1/catalog/tech-docs/` — реестр, загрузка, поток файла, удаление."""

import logging

from django.db import transaction
from django.http import Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from catalog.desk import tech_docs
from catalog.desk.audit import record
from catalog.desk.items import ItemError
from catalog.desk.serializers import DeskTechDoc, DeskTechDocUpload
from catalog.desk.views_base import FORBIDDEN, NOT_FOUND, PAGE, PAGE_SIZE, REFUSED, SEARCH, DeskViewSet, refuse
from catalog.models import TechDocument
from core.file_streaming import storage_file_response

logger = logging.getLogger(__name__)


class _Gone:
    """Удалённая запись для журнала: нужны только `pk` и подпись."""

    def __init__(self, pk, label):
        self.pk, self._label = pk, label

    def __str__(self):
        return self._label


class TechDocDeskViewSet(DeskViewSet):
    """Реестр читает любой сотрудник бэк-офиса; загрузка и удаление — `catalog.manage`."""

    required_permissions = {"create": "catalog.manage", "destroy": "catalog.manage"}
    lookup_value_regex = r"\d+"
    queryset = TechDocument.objects.none()
    serializer_class = DeskTechDoc
    parser_classes = [MultiPartParser, FormParser]

    def _doc(self, pk) -> TechDocument:
        doc = (
            TechDocument.objects.select_related("product", "deal", "deal__company", "uploaded_by").filter(pk=pk).first()
            if str(pk).isdigit()
            else None
        )
        if doc is None:
            raise NotFound()
        return doc

    @extend_schema(
        operation_id="catalog_tech_docs_list",
        summary="Technical documentation registry",
        parameters=[
            SEARCH,
            OpenApiParameter("kind", str, enum=TechDocument.Kind.values),
            OpenApiParameter("product", int, description="Id позиции номенклатуры."),
            OpenApiParameter("deal", int, description="Id заявки или проекта."),
            PAGE,
            PAGE_SIZE,
        ],
        responses={200: DeskTechDoc},
        tags=["Catalog"],
    )
    def list(self, request):
        return self.page_of(
            tech_docs.list_queryset(request.query_params), lambda rows: [tech_docs.doc_row(d) for d in rows]
        )

    @extend_schema(
        operation_id="catalog_tech_docs_create",
        summary="Upload a technical document",
        description=(
            "Needs `catalog.manage`. PDF, PNG, JPEG, DOC(X), XLS(X) до 20 МБ; содержимое сверяется с расширением. Нужна "
            "привязка к позиции (`product_id`) или заявке (`deal_id`). Коды: FILE_TOO_LARGE, FILE_TYPE_NOT_ALLOWED, "
            "FILE_CONTENT_MISMATCH, TECH_DOC_LINK_REQUIRED, PRODUCT_NOT_FOUND, DEAL_NOT_FOUND, NO_FILE_PROVIDED."
        ),
        request={"multipart/form-data": DeskTechDocUpload},
        responses={201: DeskTechDoc, 400: REFUSED, 403: FORBIDDEN},
        tags=["Catalog"],
    )
    def create(self, request):
        file = request.FILES.get("file")
        if file is None:
            return Response({"detail": "NO_FILE_PROVIDED"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                doc = tech_docs.create_doc(file, request.data, request.user)
        except ItemError as error:
            return refuse(error)
        return Response(tech_docs.doc_row(self._doc(doc.pk)), status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="catalog_tech_docs_destroy",
        summary="Delete a technical document",
        description="Needs `catalog.manage`. Файл удаляется из хранилища.",
        responses={204: None, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    def destroy(self, request, pk=None):
        doc = self._doc(pk)
        name, storage = doc.file.name, doc.file.storage
        before = {
            "title": doc.title,
            "kind": doc.kind,
            "original_name": doc.original_name,
            "size_bytes": doc.size_bytes,
        }
        doc_id = doc.pk
        with transaction.atomic():
            doc.delete()
        record(
            request.user,
            entity="tech_doc",
            instance=_Gone(doc_id, before["title"]),
            event="deleted",
            action="Файл техдокументации удалён",
            before=before,
            after=None,
            level="WARNING",
        )
        if name:
            try:
                storage.delete(name)
            except Exception:  # noqa: BLE001 — запись уже удалена; осиротевший объект хранилища не должен давать 500
                logger.exception("tech doc %s: файл %s не удалён из хранилища", doc_id, name)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="catalog_tech_docs_file",
        summary="Stream the file of a technical document",
        description=(
            "Файл потоком из приватного хранилища. PDF и изображения — `inline` (просмотр), `?download=1` и прочие "
            "форматы — вложением. Тип содержимого браузер не угадывает (`nosniff`)."
        ),
        parameters=[OpenApiParameter("download", bool, description="Отдать вложением.")],
        responses={
            (200, "application/octet-stream"): OpenApiTypes.BINARY,
            404: OpenApiResponse(description="Документа или файла нет."),
        },
        tags=["Catalog"],
    )
    @action(detail=True, methods=["get"], url_path="file")
    def file(self, request, pk=None):
        doc = self._doc(pk)
        attach = str(request.query_params.get("download", "")).lower() in ("1", "true") or not tech_docs.is_previewable(
            doc
        )
        try:
            response = storage_file_response(
                doc.file.storage,
                doc.file.name,
                content_type=doc.content_type or "application/octet-stream",
                as_attachment=attach,
                filename=doc.original_name,
            )
        except FileNotFoundError as error:
            raise Http404("File is missing in the storage") from error
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        # Как у файлов EDS: даже если файл откроют во вкладке, он не исполняет ни скрипты, ни вложенное содержимое.
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response
