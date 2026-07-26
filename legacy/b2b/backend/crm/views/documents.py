"""«Документы 2.0» ViewSets — template library + generated documents.

Thin wrappers (Rule 8): authorize → validate → ONE service call → return. All
tenant scoping is company-derived from the caller's active memberships (IDOR-safe);
platform-admin viewers are refused on every mutation via the services.
"""

from django.db.models import ProtectedError, Q
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from core.file_streaming import stream_file_field
from crm import services as crm_services
from crm.models import DocumentTemplate, GeneratedDocument
from crm.serializers import DocumentTemplateSerializer, GeneratedDocumentSerializer


class DocumentSendEmailThrottle(UserRateThrottle):
    """Per-user rate cap on document email dispatch — the platform must not become an open
    spam/phishing relay via arbitrary `to` (F2-3/MAJOR-2). Rate from settings `document_send_email`."""

    scope = "document_send_email"


class DocumentPreviewThrottle(UserRateThrottle):
    """Per-user rate cap on the template live-preview endpoint — it sanitises and renders up to
    100k of body HTML on every call with only IsAuthenticated (F3-1/III-5). Rate from settings
    `document_preview`."""

    scope = "document_preview"


def _user_company_ids(user):
    return list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))


def _brand_preview_field():
    """Inline serializer for the flat letterhead slice (T1-a) — the header/footer branding the SPA
    wraps the sanitised body in. Shared by the preview response + the generated-document serializer."""
    return inline_serializer(
        "DocumentBrandPreview",
        fields={
            "seller_name": drf_serializers.CharField(),
            "inn": drf_serializers.CharField(allow_blank=True),
            "address": drf_serializers.CharField(allow_blank=True),
            "phone": drf_serializers.CharField(allow_blank=True),
            "email": drf_serializers.CharField(allow_blank=True),
            "logo_url": drf_serializers.CharField(allow_null=True),
            "footer_text": drf_serializers.CharField(allow_blank=True),
            "accent": drf_serializers.CharField(),
            "accent_contrast": drf_serializers.CharField(),
            "signatory_name": drf_serializers.CharField(allow_blank=True),
            "signatory_position": drf_serializers.CharField(allow_blank=True),
        },
    )


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
        try:
            instance.delete()
        except ProtectedError:
            # GeneratedDocument.template is on_delete=PROTECT — a template that already produced
            # documents can't be hard-deleted (would 500). The UI offers soft-deactivation
            # (is_active=False) instead (III-1).
            return Response({"detail": "TEMPLATE_IN_USE"}, status=400)
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

    @extend_schema(
        summary="Live-preview a template body against sample data (no DB write)",
        tags=["CRM"],
        request=inline_serializer(
            "DocumentTemplatePreviewRequest",
            fields={"body_html": drf_serializers.CharField(required=False, allow_blank=True)},
        ),
        responses={
            200: inline_serializer(
                "DocumentTemplatePreview",
                fields={
                    "rendered_html": drf_serializers.CharField(),
                    "placeholders_used": drf_serializers.ListField(child=drf_serializers.CharField()),
                    "warnings": drf_serializers.ListField(child=drf_serializers.CharField()),
                    # Letterhead slice (name/ИНН/лого/подвал/accent) so the SPA renders the FULL
                    # branded document, not the bare body (T1-a).
                    "brand": _brand_preview_field(),
                    # Full branded document HTML rendered by the REAL PDF template — the 1:1 iframe
                    # preview that replaces the hand-written React letterhead.
                    "document_html": drf_serializers.CharField(),
                },
            ),
            400: OpenApiResponse(description="Validation error"),
        },
    )
    @action(detail=False, methods=["post"], url_path="preview", throttle_classes=[DocumentPreviewThrottle])
    def preview(self, request):
        """Render the editor body on sample data. Auth only — no settings.edit needed."""
        from django.core.exceptions import ValidationError as DjangoValidationError

        from accounts.models import Company

        company_id = crm_services.resolve_owner_company_id(request.user)
        if not company_id:
            return Response({"detail": "NO_COMPANY"}, status=400)
        try:
            result = crm_services.preview_template(
                Company.objects.get(pk=company_id),
                request.user,
                body_html=request.data.get("body_html", ""),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=400)
        return Response(result)

    @extend_schema(
        summary="Placeholder catalogue for the template editor (grouped)",
        tags=["CRM"],
        responses={
            200: inline_serializer(
                "DocumentPlaceholderCatalog",
                fields={
                    "groups": drf_serializers.ListField(
                        child=inline_serializer(
                            "DocumentPlaceholderGroup",
                            fields={
                                "key": drf_serializers.CharField(),
                                "label": drf_serializers.CharField(),
                                "items": drf_serializers.ListField(
                                    child=inline_serializer(
                                        "DocumentPlaceholder",
                                        fields={
                                            "code": drf_serializers.CharField(),
                                            "label": drf_serializers.CharField(),
                                        },
                                    )
                                ),
                            },
                        )
                    )
                },
            )
        },
    )
    @action(detail=False, methods=["get"], url_path="placeholders")
    def placeholders(self, request):
        """Advertised `{{code}}` placeholders in two groups (dynamic data vs company requisites
        already printed in the letterhead шапка) — the editor helper (T1-c)."""
        from crm.services.document_placeholders import PLACEHOLDER_GROUPS

        return Response({"groups": PLACEHOLDER_GROUPS})


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

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # The 1:1 preview HTML is rendered per document — only worth it on the single-object detail
        # endpoint, never for every row of the (unpaginated) list.
        context["include_document_html"] = self.action == "retrieve"
        return context

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GeneratedDocument.objects.none()
        user = self.request.user
        qs = GeneratedDocument.objects.select_related(
            "status", "template", "deal", "contact", "created_by", "company"
        ).order_by("-created_at")
        if not getattr(user, "is_platform_admin", False):
            # Own-company documents (all statuses) + ISSUED documents on deals the user reaches as a
            # PARTY — «полученные письма» read-only (II-2). A counterparty never sees another
            # company's DRAFT/CANCELLED. `.distinct()` de-dupes the seller_routings join.
            qs = qs.filter(
                Q(company_id__in=_user_company_ids(user)) | crm_services.party_visible_document_q(user)
            ).distinct()
        # Deal-scoped registry (карточка сделки → её документы; реестр «Прочие» filter), II-4.
        deal_id = self.request.query_params.get("deal")
        if deal_id:
            qs = qs.filter(deal_id=deal_id)
        return qs

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
        from crm.services.generated_documents import _user_owns_document

        instance = self.get_object()
        if is_platform_admin_viewer(request.user):
            return Response({"detail": "ADMIN_VIEWER_CANNOT_ACT"}, status=400)
        # Defence-in-depth (F2-3/MINOR-4): the widened registry queryset now surfaces counterparties'
        # ISSUED documents — only the OWNER may edit (issue/cancel already gate the same way).
        if not _user_owns_document(request.user, instance):
            return Response({"detail": "DOCUMENT_NOT_FOUND"}, status=400)
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

    @extend_schema(
        summary="Revoke the public no-login link of an issued document",
        description="Owner pulls the shared public link (post-issue). Idempotent; further public "
        "opens return 410 DOCUMENT_LINK_REVOKED. Mirrors the КП revoke-public-link.",
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="revoke-public-link")
    def revoke_public_link(self, request, pk=None):
        document, err = crm_services.revoke_document_public_link(self.get_object(), request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(self.get_serializer(document).data)

    @extend_schema(
        summary="Email an issued document to its recipient (public link in body)",
        tags=["CRM"],
        request=inline_serializer(
            "SendDocumentEmail",
            fields={"to": drf_serializers.EmailField(required=False, allow_blank=True)},
        ),
        responses={
            202: inline_serializer(
                "SendDocumentEmailResult",
                fields={"detail": drf_serializers.CharField(), "to": drf_serializers.CharField()},
            ),
            400: OpenApiResponse(description="Not issued / no recipient / not owned"),
        },
    )
    @action(detail=True, methods=["post"], url_path="send-email", throttle_classes=[DocumentSendEmailThrottle])
    def send_email(self, request, pk=None):
        to_raw = (request.data.get("to") or "").strip()
        if to_raw:
            # Validate the override as a real email — the value is passed verbatim to the mailer,
            # so an unvalidated `to` would let the owner aim the branded email anywhere (F2-3/MAJOR-2).
            try:
                drf_serializers.EmailField().run_validation(to_raw)
            except drf_serializers.ValidationError:
                return Response({"detail": "INVALID_EMAIL"}, status=400)
        recipient, err = crm_services.send_document_email(self.get_object(), request.user, to=to_raw or None)
        if err:
            return Response({"detail": err}, status=400)
        return Response({"detail": "EMAIL_QUEUED", "to": recipient}, status=202)

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
