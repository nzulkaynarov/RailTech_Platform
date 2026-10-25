"""Публичный маршрут скачивания по подписанной ссылке CRM (FIX-32, `GET /api/v1/public/doc-links/{token}/`).

Без входа: право даёт сам токен, выданный `GET /api/integration/v1/documents/{id}/link` (`services/documents_link.py`).
Токен несёт вид и id документа, вьюха голый id не принимает — перебирать нечего. Подпись, срок (10 минут) и видимость
документа проверяются на каждом открытии. Неверная подпись, чужой, скрытый и несуществующий документ — одинаковый 404;
верный токен с вышедшим сроком — 410. Файл — поток; PDF ещё не отрисован — 202 + `Retry-After`, как в портале.
Каждая выдача файла — запись журнала ERP (`document.link_downloaded`). Лимит частоты — общий с публичными ссылками.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from portal.services import documents as portal_documents
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .services import documents_link


class PublicDocumentLinkView(APIView):
    """GET по подписанному токену: файл документа потоком."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_document"

    @extend_schema(
        summary="Файл документа по подписанной ссылке CRM (FIX-32)",
        responses={
            200: OpenApiResponse(description="Файл документа"),
            202: OpenApiResponse(description="PDF ещё рисуется — повторить через Retry-After секунд"),
            404: OpenApiResponse(description="Подпись не сошлась или документ недоступен"),
            410: OpenApiResponse(description="Срок ссылки (10 минут) вышел"),
        },
        tags=["Portal"],
    )
    def get(self, request, token):
        try:
            link = documents_link.resolve_link_token(token)
        except documents_link.LinkExpired:
            return Response({"detail": "DOCUMENT_LINK_EXPIRED"}, status=status.HTTP_410_GONE)
        except documents_link.LinkNotFound:
            return Response({"detail": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        document = link.document
        response = portal_documents.ready_file_response(document)
        if response is None and not portal_documents.renders_on_demand(document):
            return Response({"detail": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if response is None:
            portal_documents.enqueue_render(document)
            return Response(
                {"detail": "DOCUMENT_PENDING"},
                status=status.HTTP_202_ACCEPTED,
                headers={"Retry-After": str(portal_documents.RETRY_AFTER_SECONDS)},
            )

        documents_link.record_download(link, ip=request.META.get("REMOTE_ADDR", "") or "")
        response["Cache-Control"] = "private, no-store"  # ссылка с секретом: прокси и браузер файл не хранят
        return response
