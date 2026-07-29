"""N2 document-numbering-scheme editor endpoints (Settings → «Нумерация»).

Thin wrappers (Rule 8): authorize → validate shape → call ONE service → return.
ALL numbering logic (mask token rendering, effectiveness/global-unique invariant,
draft validation) lives in ``crm.services.numbering``.

Gate: identical to the other company-settings writes — the actor must hold the
`settings.edit` CompanyRole permission (via `is_company_owner`) on their OWN SELLER
company. A pure buyer / non-seller has no such company → 403.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.services.document_profile import is_company_owner
from accounts.services.permissions import primary_seller_company_id

from ..serializers import (
    NumberingPreviewRequestSerializer,
    NumberingPreviewResponseSerializer,
    NumberingSchemeSerializer,
    NumberingSchemeWriteSerializer,
)
from ..services.numbering import get_company_scheme_view, preview_scheme_numbers, set_company_scheme


def _resolve_seller_company(user):
    """The actor's OWN seller company (prefers primary membership), or None.

    Numbering is a per-seller-company setting; a buyer / non-seller resolves to None
    and is refused. Mirrors how КП preparation anchors on the primary seller company.
    """
    from accounts.models import Company

    company_id = primary_seller_company_id(user)
    if company_id is None:
        return None
    return Company.objects.filter(id=company_id).first()


def _authorized_company_or_403(request):
    """Resolve + gate the actor's seller company. Returns (company, None) on success,
    else (None, Response) with a 403 `{"detail": CODE}`."""
    company = _resolve_seller_company(request.user)
    if company is None:
        return None, Response({"detail": "SELLER_COMPANY_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)
    if not is_company_owner(request.user, company):
        return None, Response({"detail": "SETTINGS_EDIT_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)
    return company, None


def _scheme_view_payload(company) -> dict:
    """Flatten the SchemeView dataclass into the serializer's field shape."""
    view = get_company_scheme_view(company)
    return {
        "pattern": view.scheme.pattern,
        "padding": view.scheme.padding,
        "reset_period": view.scheme.reset_period,
        "start_value": view.scheme.start_value,
        "prefix": view.prefix,
        "is_effective": view.is_effective,
        "type_labels": view.scheme.type_labels,
    }


class NumberingSchemeView(APIView):
    """GET/PATCH the acting seller company's document-numbering scheme.
    GET/PATCH /api/v1/crm/numbering-scheme/"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Read effective numbering scheme",
        description=(
            "The acting seller company's EFFECTIVE numbering scheme (mask/padding/reset/"
            "start) plus its brand `prefix` and `is_effective` (whether a custom scheme "
            "actually mints — only true with a non-empty prefix). settings.edit + seller only."
        ),
        responses={200: NumberingSchemeSerializer, 403: OpenApiResponse(description="Not a seller / no settings.edit")},
        tags=["CRM"],
    )
    def get(self, request):
        company, denied = _authorized_company_or_403(request)
        if denied is not None:
            return denied
        return Response(NumberingSchemeSerializer(_scheme_view_payload(company)).data)

    @extend_schema(
        summary="Update numbering scheme",
        description=(
            "Upsert the seller company's numbering scheme. An invalid mask (missing {seq}, "
            'empty) → 400 {"detail": "INVALID_NUMBERING_PATTERN"}. Applies to FUTURE numbers '
            "only; already-issued numbers are snapshots and never change. settings.edit + seller."
        ),
        request=NumberingSchemeWriteSerializer,
        responses={
            200: NumberingSchemeSerializer,
            400: OpenApiResponse(description="INVALID_NUMBERING_PATTERN"),
            403: OpenApiResponse(description="Not a seller / no settings.edit"),
        },
        tags=["CRM"],
    )
    def patch(self, request):
        company, denied = _authorized_company_or_403(request)
        if denied is not None:
            return denied
        write = NumberingSchemeWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        try:
            set_company_scheme(company, **write.validated_data)
        except DjangoValidationError:
            return Response({"detail": "INVALID_NUMBERING_PATTERN"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(NumberingSchemeSerializer(_scheme_view_payload(company)).data)


class NumberingSchemePreviewView(APIView):
    """POST a DRAFT scheme → rendered example КП/CT/INV numbers (dry-run, no counter write).
    POST /api/v1/crm/numbering-scheme/preview/"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Preview numbering scheme (dry-run)",
        description=(
            "Render example КП/CT/INV numbers for a DRAFT scheme WITHOUT touching any "
            "counter — the live editor preview. Uses the same token parser as real minting "
            "(single source of truth). Invalid mask → 400 INVALID_NUMBERING_PATTERN."
        ),
        request=NumberingPreviewRequestSerializer,
        responses={
            200: NumberingPreviewResponseSerializer,
            400: OpenApiResponse(description="INVALID_NUMBERING_PATTERN"),
            403: OpenApiResponse(description="Not a seller / no settings.edit"),
        },
        tags=["CRM"],
    )
    def post(self, request):
        company, denied = _authorized_company_or_403(request)
        if denied is not None:
            return denied
        draft = NumberingPreviewRequestSerializer(data=request.data)
        draft.is_valid(raise_exception=True)
        try:
            results = preview_scheme_numbers(company, **draft.validated_data)
        except DjangoValidationError:
            return Response({"detail": "INVALID_NUMBERING_PATTERN"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"results": results})
