"""Logo, document-profile and КП-settings actions for ``CompanyViewSet``.

Split out of the monolithic ``accounts/views/company.py`` (file-length refactor,
500-line rule) as a mixin — behaviour, ``url_path``/``url_name``, parsers and
permissions are unchanged. Mixed into ``CompanyViewSet``, which supplies
``get_object`` and the ``_assert_member_or_admin`` helper; this class only adds
``@action`` methods. Upload validators (``core/validators.py``, magic-byte checks)
are preserved verbatim.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts import services
from accounts.serializers import (
    CompanyDocumentProfileSerializer,
    CompanySerializer,
    CompanySettingsSerializer,
    CompanySettingsUpdateSerializer,
)


class CompanyDocumentsMixin:
    """Logo, document-profile and КП-settings ``@action`` endpoints."""

    @extend_schema(
        summary="Upload company logo",
        description="Upload or replace a company's logo (multipart/form-data).",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "logo": {"type": "string", "format": "binary"},
                },
            }
        },
        responses={
            200: CompanySerializer,
            400: OpenApiResponse(description="NO_FILE_PROVIDED (or the upload validator's message)"),
        },
        tags=["Accounts"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="upload-logo",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_logo(self, request, pk=None):
        company = self.get_object()
        self._assert_member_or_admin(company)
        logo_file = request.FILES.get("logo")
        if not logo_file:
            return Response({"detail": "NO_FILE_PROVIDED"}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.exceptions import ValidationError

        from core.validators import validate_image_upload

        try:
            validate_image_upload(logo_file)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if company.logo:
            company.logo.delete(save=False)
        company.logo = logo_file
        company.save(update_fields=["logo"])
        return Response(CompanySerializer(company, context={"request": request}).data)

    @extend_schema(
        summary="Delete company logo",
        responses={204: None},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["delete"], url_path="delete-logo")
    def delete_logo(self, request, pk=None):
        company = self.get_object()
        self._assert_member_or_admin(company)
        if company.logo:
            company.logo.delete(save=False)
            company.logo = None
            company.save(update_fields=["logo"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Read / update company document profile",
        description=(
            "The branded requisites a company prints on its own КП / contract documents "
            "(legal name, ИНН, юр.адрес, банк, подписант, колонтитул, акцентный цвет). "
            "GET returns the profile (auto-created); PATCH updates it. OWNER of THIS company "
            "(or platform admin) only — never another tenant. Logo is uploaded separately."
        ),
        request=CompanyDocumentProfileSerializer,
        responses={
            200: CompanyDocumentProfileSerializer,
            400: OpenApiResponse(
                description="INVALID_ACCENT_COLOR / INVALID_SECONDARY_COLOR / INVALID_LAYOUT_PRESET / INVALID_FONT_FAMILY"
            ),
            403: OpenApiResponse(description="NOT_COMPANY_OWNER: only the company OWNER may read/update the profile"),
        },
        tags=["Accounts"],
    )
    @action(detail=True, methods=["get", "patch"], url_path="document-profile")
    def document_profile(self, request, pk=None):
        company = self.get_object()
        if not services.is_company_owner(request.user, company):
            return Response({"detail": "NOT_COMPANY_OWNER"}, status=status.HTTP_403_FORBIDDEN)
        if request.method == "PATCH":
            profile, error = services.update_document_profile(request.user, company, request.data)
            if error:
                http_status = status.HTTP_403_FORBIDDEN if error == "NOT_COMPANY_OWNER" else status.HTTP_400_BAD_REQUEST
                return Response({"detail": error}, status=http_status)
        else:
            profile = services.get_document_profile(company)
        return Response(CompanyDocumentProfileSerializer(profile, context={"request": request}).data)

    @extend_schema(
        summary="Live preview of a sample document with the company's theme (Document Layout)",
        description="Renders a SAMPLE document of the requested kind (КП / договор / инвойс / "
        "акт / письмо) as HTML using the company's document profile. POST body may carry "
        "{doc_type, draft:{...}} — the draft overlays UNSAVED theme settings in-memory (never "
        "saved), so the editor previews live like the Odoo Document-Layout wizard. GET stays "
        "the legacy saved-profile КП preview. OWNER only. Returns text/html (no WeasyPrint in "
        "the request thread, ARCH-03).",
        request=inline_serializer(
            "DocumentProfilePreviewRequest",
            fields={
                "doc_type": serializers.ChoiceField(choices=["KP", "CT", "INV", "ACT", "DOC"], required=False),
                "draft": serializers.DictField(
                    required=False, help_text="Unsaved document-profile fields overlaid in memory (never saved)"
                ),
            },
        ),
        responses={
            (200, "text/html"): OpenApiTypes.STR,
            400: OpenApiResponse(description="INVALID_PREVIEW_DOC_TYPE (POST only)"),
            403: OpenApiResponse(description="NOT_COMPANY_OWNER"),
        },
        tags=["Accounts"],
    )
    @action(detail=True, methods=["get", "post"], url_path="document-profile/preview")
    def document_profile_preview(self, request, pk=None):
        from django.http import HttpResponse

        from crm.services.documents import PREVIEW_DOC_TYPES, render_document_profile_preview_html

        company = self.get_object()
        if not services.is_company_owner(request.user, company):
            return Response({"detail": "NOT_COMPANY_OWNER"}, status=status.HTTP_403_FORBIDDEN)
        doc_type = "KP"
        overrides = None
        if request.method == "POST":
            doc_type = request.data.get("doc_type") or "KP"
            if doc_type not in PREVIEW_DOC_TYPES:
                return Response({"detail": "INVALID_PREVIEW_DOC_TYPE"}, status=status.HTTP_400_BAD_REQUEST)
            draft = request.data.get("draft")
            overrides = draft if isinstance(draft, dict) else None
        html = render_document_profile_preview_html(company, doc_type=doc_type, overrides=overrides)
        return HttpResponse(html, content_type="text/html; charset=utf-8")

    @extend_schema(
        summary="Upload company document-profile logo",
        description="Upload or replace the logo printed in the КП / contract header (multipart/form-data). OWNER only.",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {"logo": {"type": "string", "format": "binary"}},
            }
        },
        responses={
            200: CompanyDocumentProfileSerializer,
            400: OpenApiResponse(description="NO_FILE_PROVIDED / INVALID_IMAGE (or the upload validator's message)"),
            403: OpenApiResponse(description="NOT_COMPANY_OWNER"),
        },
        tags=["Accounts"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="document-profile/upload-logo",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_document_profile_logo(self, request, pk=None):
        company = self.get_object()
        profile, error = services.upload_document_profile_logo(request.user, company, request.FILES.get("logo"))
        if error:
            http_status = status.HTTP_403_FORBIDDEN if error == "NOT_COMPANY_OWNER" else status.HTTP_400_BAD_REQUEST
            return Response({"detail": error}, status=http_status)
        return Response(CompanyDocumentProfileSerializer(profile, context={"request": request}).data)

    @extend_schema(
        summary="Read / update company КП defaults + numbering",
        description=(
            "The selling company's КП defaults (Incoterm, валюта себестоимости, ставка НДС, "
            "маржа, срок действия) and its document-numbering prefix. GET returns the settings "
            "(auto-created); PATCH updates them. delivery_basis / cost_currency are sent as "
            "master-data CODES (e.g. 'USD', 'FCA'). OWNER of THIS company (or platform admin) only. "
            "`payment_terms_days` is the invoice payment term in days (0..32767, null = platform default)."
        ),
        request=CompanySettingsUpdateSerializer,
        responses={
            200: CompanySettingsSerializer,
            400: OpenApiResponse(
                description="BAD_CURRENCY / BAD_DELIVERY_BASIS / BAD_NUMBER / BAD_PRICE_VISIBILITY / "
                "BAD_PUBLISH_THRESHOLD / BAD_FX_RATE_MAX_AGE_DAYS / DOC_PREFIX_TAKEN"
            ),
            403: OpenApiResponse(description="NOT_COMPANY_OWNER: only the company OWNER may read/update the settings"),
        },
        tags=["Accounts"],
    )
    @action(detail=True, methods=["get", "patch"], url_path="settings")
    def company_settings(self, request, pk=None):
        company = self.get_object()
        if not services.is_company_owner(request.user, company):
            return Response({"detail": "NOT_COMPANY_OWNER"}, status=status.HTTP_403_FORBIDDEN)
        if request.method == "PATCH":
            settings_row, error = services.update_company_settings(request.user, company, request.data)
            if error:
                http_status = status.HTTP_403_FORBIDDEN if error == "NOT_COMPANY_OWNER" else status.HTTP_400_BAD_REQUEST
                return Response({"detail": error}, status=http_status)
        else:
            settings_row = services.get_company_settings(company)
        return Response(CompanySettingsSerializer(settings_row, context={"request": request}).data)
