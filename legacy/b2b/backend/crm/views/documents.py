"""«Документы 2.0» ViewSets — template library + generated documents.

Thin wrappers (Rule 8): authorize → validate → ONE service call → return. All
tenant scoping is company-derived from the caller's active memberships (IDOR-safe);
platform-admin viewers are refused on every mutation via the services.
"""

from django.db.models import Q
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.file_streaming import stream_file_field
from crm import services as crm_services
from crm.models import DocumentTemplate, GeneratedDocument
from crm.serializers import DocumentTemplateSerializer, GeneratedDocumentSerializer


def _user_company_ids(user):
    return list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))


class DocumentTemplateViewSet(viewsets.ModelViewSet):
    """Company template library. Read = own templates + platform samples («скопировать
    к себе»); write is gated on the `settings.edit` CompanyRole permission and limited
    to the caller's own company (never samples, never another tenant)."""

    serializer_class = DocumentTemplateSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if not getattr(self, "swagger_fake_view", False):
            context["owner_company_id"] = crm_services.resolve_owner_company_id(self.request.user)
        return context

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DocumentTemplate.objects.none()
        owner_company_id = crm_services.resolve_owner_company_id(self.request.user)
        # Own templates + global samples (readable by all, copy-source only).
        return (
            DocumentTemplate.objects.filter(Q(company_id=owner_company_id) | Q(company__isnull=True, is_sample=True))
            .select_related("kind", "company")
            .order_by("-is_sample", "name")
        )

    def _owner_company(self):
        from accounts.models import Company
        from accounts.services.permissions import member_has_permission

        user = self.request.user
        company_id = crm_services.resolve_owner_company_id(user)
        if not company_id:
            raise PermissionDenied("NO_COMPANY")
        if not (getattr(user, "is_superuser", False) or member_has_permission(user, company_id, "settings.edit")):
            raise PermissionDenied("SETTINGS_EDIT_REQUIRED")
        return Company.objects.get(pk=company_id)

    def _assert_owned(self, instance):
        owner_company_id = crm_services.resolve_owner_company_id(self.request.user)
        if instance.company_id is None or instance.company_id != owner_company_id:
            raise PermissionDenied("TEMPLATE_NOT_EDITABLE")

    def create(self, request, *args, **kwargs):
        company = self._owner_company()
        template = crm_services.create_template(
            company,
            request.user,
            name=request.data.get("name", ""),
            kind_code=request.data.get("kind", "CUSTOM"),
            body_html=request.data.get("body_html", ""),
        )
        return Response(self.get_serializer(template).data, status=201)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        self._owner_company()  # gate on settings.edit
        self._assert_owned(instance)
        template = crm_services.update_template(
            instance,
            name=request.data.get("name"),
            kind_code=request.data.get("kind"),
            body_html=request.data.get("body_html"),
            is_active=request.data.get("is_active"),
        )
        return Response(self.get_serializer(template).data)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self._owner_company()
        self._assert_owned(instance)
        instance.delete()
        return Response(status=204)

    @extend_schema(summary="Copy a platform sample into the caller's company", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="copy")
    def copy(self, request, pk=None):
        source = self.get_object()
        company = self._owner_company()
        template = crm_services.create_template(
            company,
            request.user,
            name=source.name,
            kind_code=source.kind.code,
            body_html=source.body_html,
        )
        return Response(self.get_serializer(template).data, status=201)


class GeneratedDocumentViewSet(viewsets.ModelViewSet):
    """Rendered documents registry. List/retrieve are company-scoped; generation and
    status transitions run in services (entitlement + IDOR + viewer gates)."""

    serializer_class = GeneratedDocumentSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]
    # No pagination: the SPA registry does client-side filter/sort/paging + computes stat tiles over
    # the full set (mirrors DocumentTemplateViewSet). Default paging would silently cap at 20 rows and
    # understate the counts (A4/M3).
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GeneratedDocument.objects.none()
        user = self.request.user
        qs = GeneratedDocument.objects.select_related(
            "status", "template", "deal", "contact", "created_by", "company"
        ).order_by("-created_at")
        if getattr(user, "is_platform_admin", False):
            return qs
        return qs.filter(company_id__in=_user_company_ids(user))

    def _readable_template(self, template_id):
        owner_company_id = crm_services.resolve_owner_company_id(self.request.user)
        return (
            DocumentTemplate.objects.filter(Q(company_id=owner_company_id) | Q(company__isnull=True, is_sample=True))
            .filter(pk=template_id)
            .first()
        )

    @extend_schema(
        summary="Generate a document from a template",
        tags=["CRM"],
        request=inline_serializer(
            "GenerateDocument",
            fields={
                "template_id": drf_serializers.IntegerField(),
                "deal_id": drf_serializers.IntegerField(required=False),
                "contact_id": drf_serializers.IntegerField(required=False),
                "title": drf_serializers.CharField(required=False),
            },
        ),
        responses={201: GeneratedDocumentSerializer, 400: OpenApiResponse(description="Validation error")},
    )
    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        from accounts.models import Company, Contact
        from crm.models import Deal

        template_id = request.data.get("template_id")
        if not template_id:
            return Response({"detail": "TEMPLATE_ID_REQUIRED"}, status=400)
        template = self._readable_template(template_id)
        if template is None:
            return Response({"detail": "TEMPLATE_NOT_FOUND"}, status=400)
        owner_company_id = crm_services.resolve_owner_company_id(request.user)
        if not owner_company_id:
            return Response({"detail": "NO_COMPANY"}, status=400)

        deal = Deal.objects.filter(pk=request.data.get("deal_id")).first() if request.data.get("deal_id") else None
        contact = (
            Contact.objects.filter(pk=request.data.get("contact_id")).first()
            if request.data.get("contact_id")
            else None
        )
        if request.data.get("deal_id") and deal is None:
            return Response({"detail": "DEAL_NOT_FOUND"}, status=400)
        if request.data.get("contact_id") and contact is None:
            return Response({"detail": "CONTACT_NOT_FOUND"}, status=400)

        document, err = crm_services.generate_document(
            Company.objects.get(pk=owner_company_id),
            request.user,
            template=template,
            deal=deal,
            contact=contact,
            title=request.data.get("title"),
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(self.get_serializer(document).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        """Edit a DRAFT document's placeholder values (re-render + PDF invalidation)."""
        from accounts.services import is_platform_admin_viewer

        instance = self.get_object()
        if is_platform_admin_viewer(request.user):
            return Response({"detail": "ADMIN_VIEWER_CANNOT_ACT"}, status=400)
        document, err = crm_services.update_document_values(instance, request.data.get("values", {}))
        if err:
            return Response({"detail": err}, status=400)
        return Response(self.get_serializer(document).data)

    @extend_schema(summary="Issue a draft document (freeze + render PDF)", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="issue")
    def issue(self, request, pk=None):
        document, err = crm_services.issue_document(self.get_object(), request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(self.get_serializer(document).data)

    @extend_schema(summary="Cancel a document", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        document, err = crm_services.cancel_document(self.get_object(), request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(self.get_serializer(document).data)

    @extend_schema(summary="Download the document PDF (202 + enqueue if not ready)", tags=["CRM"])
    @action(detail=True, methods=["get"], url_path="download-pdf")
    def download_pdf(self, request, pk=None):
        document = self.get_object()
        # A cancelled document is not a deliverable — never (re-)render or serve its PDF (A4/m7).
        if document.status_code == "CANCELLED":
            return Response({"detail": "DOCUMENT_CANCELLED"}, status=409)
        if not document.pdf_file:
            from crm.views._pdf import pdf_generating_response

            return pdf_generating_response("generated", document.id)
        return stream_file_field(document.pdf_file)
