"""`/api/v1/settings/legal-editions/` и `/settings/legal-acceptances/` — редакции оферты и политики Кабинета (ДВ-5).

Всё — под правом `settings.edit` (правило компании, его правят директор и администратор), в том числе чтение: в журнале
акцептов лежат имена и адреса контактов клиентов.
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from portal.desk.serializers_legal import (
    DeskLegalAcceptance,
    DeskLegalEditionCreateIn,
    DeskLegalEditionDetail,
    DeskLegalEditionList,
    DeskLegalEditionUpdateIn,
)
from portal.exceptions import PortalBadRequest
from portal.models_legal import LegalAcceptance, LegalEdition
from portal.services import legal as service
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.services.permissions import staff_has_permission
from catalog.desk.views_base import FORBIDDEN, NOT_FOUND, REFUSED, DeskViewSet
from core.permissions import ROLE_NOT_PERMITTED

EDIT = "settings.edit"
CONFLICT = OpenApiResponse(
    description="Черновик этого вида уже есть (`LEGAL_DRAFT_EXISTS`), редакция уже опубликована (`LEGAL_EDITION_PUBLISHED`) или метка занята (`LEGAL_LABEL_TAKEN`)."
)


def _allowed(user) -> bool:
    return bool(user.is_superuser or staff_has_permission(user, EDIT))


def _denied() -> Response:
    return Response({"detail": ROLE_NOT_PERMITTED}, status=status.HTTP_403_FORBIDDEN)


def _not_found() -> Response:
    return Response({"detail": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)


class LegalEditionDeskViewSet(DeskViewSet):
    required_permissions = {
        "create": EDIT,
        "partial_update": EDIT,
        "destroy": EDIT,
        "publish_edition": EDIT,
    }
    lookup_value_regex = r"\d+"
    queryset = LegalEdition.objects.none()
    serializer_class = DeskLegalEditionDetail
    pagination_class = None

    def _detail(self, edition: LegalEdition) -> Response:
        return Response(service.edition_detail(edition))

    @extend_schema(
        operation_id="settings_legal_editions_list",
        summary="List cabinet legal editions",
        description="Редакции оферты и политики Кабинета по видам: статус, кто и когда опубликовал, число акцептов.",
        responses={200: DeskLegalEditionList, 403: FORBIDDEN},
        tags=["Settings"],
    )
    def list(self, request):
        if not _allowed(request.user):
            return _denied()
        return Response({"results": service.editions_overview()})

    @extend_schema(
        operation_id="settings_legal_editions_retrieve",
        summary="Get a cabinet legal edition",
        description="Текст редакции на трёх языках: как написан и с подстановками реквизитов компании.",
        responses={200: DeskLegalEditionDetail, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Settings"],
    )
    def retrieve(self, request, pk=None):
        if not _allowed(request.user):
            return _denied()
        edition = LegalEdition.objects.filter(pk=pk).first()
        return self._detail(edition) if edition else _not_found()

    @extend_schema(
        operation_id="settings_legal_editions_create",
        summary="Create a draft edition",
        description="Новая редакция — черновик, копия действующей. Черновик одного вида — один.",
        request=DeskLegalEditionCreateIn,
        responses={201: DeskLegalEditionDetail, 400: REFUSED, 403: FORBIDDEN, 409: CONFLICT},
        tags=["Settings"],
    )
    def create(self, request):
        body = DeskLegalEditionCreateIn(data=request.data)
        body.is_valid(raise_exception=True)
        edition = service.create_draft(body.validated_data["kind"], actor=request.user)
        return Response(service.edition_detail(edition), status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="settings_legal_editions_update",
        summary="Edit a draft edition",
        description="Меняет метку и текст черновика. Опубликованную редакцию править нельзя — создайте новую.",
        request=DeskLegalEditionUpdateIn,
        responses={200: DeskLegalEditionDetail, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND, 409: CONFLICT},
        tags=["Settings"],
    )
    def partial_update(self, request, pk=None):
        body = DeskLegalEditionUpdateIn(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        try:
            edition = service.update_draft(
                int(pk), content=request.data.get("content"), label=body.validated_data.get("label")
            )
        except LegalEdition.DoesNotExist:
            return _not_found()
        return self._detail(edition)

    @extend_schema(
        operation_id="settings_legal_editions_destroy",
        summary="Discard a draft edition",
        responses={204: OpenApiResponse(description="Черновик удалён."), 403: FORBIDDEN, 404: NOT_FOUND, 409: CONFLICT},
        tags=["Settings"],
    )
    def destroy(self, request, pk=None):
        try:
            service.discard_draft(int(pk))
        except LegalEdition.DoesNotExist:
            return _not_found()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="settings_legal_editions_publish",
        summary="Publish a draft edition",
        description=(
            "Делает черновик действующей редакцией, прежняя действующая этого вида снимается. С этого момента все контакты "
            "Кабинета принимают новую редакцию при следующем входе; открытые сессии закрываются экраном принятия."
        ),
        request=None,
        responses={200: DeskLegalEditionDetail, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND, 409: CONFLICT},
        tags=["Settings"],
    )
    @action(detail=True, methods=["post"], url_path="publish", url_name="publish")
    def publish_edition(self, request, pk=None):
        try:
            edition = service.release_edition(int(pk), actor=request.user)
        except LegalEdition.DoesNotExist:
            return _not_found()
        return self._detail(edition)


class LegalAcceptanceDeskViewSet(DeskViewSet):
    required_permissions: dict = {}
    queryset = LegalAcceptance.objects.none()
    serializer_class = DeskLegalAcceptance

    @extend_schema(
        operation_id="settings_legal_acceptances_list",
        summary="List cabinet legal acceptances",
        description="Журнал акцептов: кто из контактов, когда и какую редакцию принял. Только чтение.",
        parameters=[
            OpenApiParameter("edition", int, required=False, description="Только акцепты этой редакции."),
            OpenApiParameter(
                "q", str, required=False, description="Поиск по имени и адресу контакта и названию компании."
            ),
        ],
        responses={200: DeskLegalAcceptance(many=True), 403: FORBIDDEN},
        tags=["Settings"],
    )
    def list(self, request):
        if not _allowed(request.user):
            return _denied()
        rows = service.acceptances_page()
        edition = request.query_params.get("edition")
        if edition:
            if not edition.isdigit():
                raise PortalBadRequest("VALIDATION_ERROR")
            rows = rows.filter(edition_id=int(edition))
        q = (request.query_params.get("q") or "").strip()
        if q:
            from django.db.models import Q

            rows = rows.filter(
                Q(contact__name__icontains=q) | Q(contact__email__icontains=q) | Q(company__name__icontains=q)
            )
        return self.page_of(rows, lambda page: [service.acceptance_row(item) for item in page])
