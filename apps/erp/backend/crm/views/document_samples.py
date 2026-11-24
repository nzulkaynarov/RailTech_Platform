"""Sample document of the settings screens (ДОК-14): queue the real generator, read its state, download the PDF.

Thin wrappers (Rule 8): the work is `crm.services.documents.sample`. The sample is rendered by a worker; the screen asks
for it once, polls the state and downloads the PDF into its viewer.
"""

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from core.permissions import RoleGatedViewMixin
from crm import services as crm_services
from crm.services.documents import sample as sample_service


class DocumentSampleThrottle(UserRateThrottle):
    """Per-user cap on sample requests: every one is a render in the PDF queue. Rate from settings `document_preview`."""

    scope = "document_preview"


_STATE = inline_serializer(
    "DocumentSampleState",
    # Keyword form: `error` here is the state field of the sample (a code), not a hand-written HTTP error body.
    fields=dict(
        id=drf_serializers.CharField(),
        status=drf_serializers.CharField(help_text="pending | ready | failed"),
        warnings=drf_serializers.ListField(
            child=drf_serializers.CharField(), required=False, help_text="Коды подстановок текста, которых нет"
        ),
        error=drf_serializers.CharField(required=False, help_text="Код ошибки при status=failed"),
    ),
)


def _state_body(sample_id: str, state: dict) -> dict:
    return {"id": sample_id, **state}


class DocumentSampleViewSet(RoleGatedViewMixin, viewsets.ViewSet):
    """Sample document of the settings screens: queue, state, PDF.

    `settings.edit` is checked explicitly on every action: the role gate lets safe methods (GET) through. A sample is
    visible only to the user who asked for it.
    """

    required_permissions = {"create": "settings.edit", "retrieve": "settings.edit", "pdf": "settings.edit"}
    lookup_value_regex = "[0-9a-f]{32}"

    def get_throttles(self):
        # Only asking costs a render; the screen polls the state every second or two.
        return [DocumentSampleThrottle()] if self.action == "create" else []

    def _company_id(self, request):
        return crm_services.resolve_owner_company_id(request.user)

    def _allowed_company(self, request):
        """The company of the caller when the caller may edit its settings, else None."""
        from accounts.services.permissions import member_has_permission

        company_id = self._company_id(request)
        if company_id and member_has_permission(request.user, company_id, "settings.edit"):
            return company_id
        return None

    @extend_schema(
        summary="Queue a sample document made by the real generator",
        description="Образец документа строит тот же генератор и та же нумерация, что и рабочий документ: бланк компании "
        "(или несохранённый черновик `draft`), действующий шаблон (или несохранённый текст `body_html`), номер — тот, "
        "что получил бы следующий документ, счётчик не занимается. PDF рендерит воркер.",
        request=inline_serializer(
            "DocumentSampleRequest",
            fields={
                "kind": drf_serializers.CharField(
                    required=False, help_text="KP, CT, INV, ACT, DOC: КП, договор, счёт, акт, письмо"
                ),
                "template_kind": drf_serializers.CharField(
                    required=False,
                    help_text="Код вида шаблона (CONTRACT, INVOICE, ACT; иной — письмо) вместо `kind`: образец текста "
                    "из редактора шаблонов.",
                ),
                "body_html": drf_serializers.CharField(required=False, allow_blank=True),
                "draft": drf_serializers.DictField(required=False, help_text="Несохранённые поля бланка"),
                "language": drf_serializers.CharField(
                    required=False, help_text="ru, en, uz: язык печати; по умолчанию — язык платформы"
                ),
            },
        ),
        responses={
            202: _STATE,
            400: OpenApiResponse(description="NO_COMPANY / INVALID_SAMPLE_KIND (error code)"),
        },
        tags=["CRM"],
    )
    def create(self, request):
        company_id = self._company_id(request)
        if not company_id:
            return Response({"detail": "NO_COMPANY"}, status=400)
        if self._allowed_company(request) is None:
            raise PermissionDenied()
        data = request.data
        kind = data.get("kind")
        if kind is None and data.get("template_kind") is not None:
            template_kind = data.get("template_kind")
            kind = (
                sample_service.TEMPLATE_KIND_SAMPLE.get(template_kind, "DOC")
                if isinstance(template_kind, str)
                else None
            )
        body_html = data.get("body_html")
        draft = data.get("draft")
        language = data.get("language")
        if (
            not isinstance(kind, str)
            or (body_html is not None and not isinstance(body_html, str))
            or (language is not None and not isinstance(language, str))
        ):
            return Response({"detail": "INVALID_SAMPLE_KIND"}, status=400)
        from accounts.models import Company

        try:
            sample_id = sample_service.queue_sample(
                Company.objects.get(pk=company_id),
                request.user,
                {
                    "kind": kind,
                    "body_html": body_html,
                    "draft": draft,
                    "language": language,
                },
            )
        except sample_service.SampleError as exc:
            return Response({"detail": exc.code}, status=400)
        return Response(_state_body(sample_id, {"status": "pending"}), status=202)

    @extend_schema(
        summary="State of a sample document",
        responses={200: _STATE, 404: OpenApiResponse(description="SAMPLE_NOT_FOUND: unknown or expired")},
        tags=["CRM"],
    )
    def retrieve(self, request, pk=None):
        company_id = self._allowed_company(request)
        if company_id is None:
            raise PermissionDenied()
        state = sample_service.sample_state(company_id, request.user.pk, pk)
        if state is None:
            return Response({"detail": "SAMPLE_NOT_FOUND"}, status=404)
        return Response(_state_body(pk, state))

    @extend_schema(
        summary="PDF of a ready sample document",
        responses={
            (200, "application/pdf"): OpenApiResponse(description="PDF"),
            404: OpenApiResponse(description="SAMPLE_NOT_FOUND: not ready, unknown or expired"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="pdf")
    def pdf(self, request, pk=None):
        company_id = self._allowed_company(request)
        if company_id is None:
            raise PermissionDenied()
        data = sample_service.sample_pdf(company_id, request.user.pk, pk)
        if data is None:
            return Response({"detail": "SAMPLE_NOT_FOUND"}, status=404)
        response = HttpResponse(data, content_type="application/pdf")
        response["Content-Disposition"] = 'inline; filename="sample.pdf"'
        return response
