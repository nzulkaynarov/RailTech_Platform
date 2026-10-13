"""KYC verification + offline-company merge actions for ``CompanyViewSet``.

Split out of the monolithic ``accounts/views/company.py`` (file-length refactor,
500-line rule) as a mixin — behaviour, ``url_path``/``url_name`` and permissions
are unchanged. Mixed into ``CompanyViewSet`` (which supplies queryset, serializer,
``get_object`` and the operator-permission map); this class only adds ``@action`` methods.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts import services
from accounts.constants import VerificationStatusCode
from accounts.models import Company
from accounts.serializers import KYCVerificationSerializer
from core.permissions import IsPlatformAdmin


class CompanyKYCMixin:
    """KYC verification and offline-duplicate merge ``@action`` endpoints."""

    @extend_schema(
        summary="Verify company KYC",
        description=(
            "Update KYC verification status for a company. "
            "Pass a VerificationStatus code (e.g. 'L2_VERIFIED') and optional comment."
        ),
        request=KYCVerificationSerializer,
        responses={
            200: OpenApiResponse(description="Status updated successfully"),
            400: OpenApiResponse(description="Validation error or business rule violation"),
        },
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="verify-kyc")
    def verify_kyc(self, request, pk=None):
        company = self.get_object()
        serializer = KYCVerificationSerializer(data=request.data)
        if serializer.is_valid():
            code = serializer.validated_data["status_code"]
            comment = serializer.validated_data.get("comment", "")
            reason = (request.data.get("reason") or comment or "").strip()

            # Policy (owner decision 2026-06-03): admins may approve KYC without
            # requiring uploaded documents. The require_documents capability stays
            # in the service for future tightening.
            result, error = services.verify_company_kyc(
                company,
                request.user,
                level_code=code,
                require_documents=False,
                reason=reason,
            )
            if error:
                return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

            if comment:
                result.kyc_notes = comment
                result.save(update_fields=["kyc_notes"])

            return Response({"status": "Status updated", "new_status": result.verification_status.name})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Duplicate offline companies (merge candidates)",
        description="Platform Admin: offline placeholder companies whose stated INN matches this "
        "company's canonical INN — candidates to fold in via merge (CRM Phase C).",
        responses={200: OpenApiResponse(description="List of {id, name, stated_inn, is_registered}")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["get"], url_path="merge-candidates", permission_classes=[IsPlatformAdmin])
    def merge_candidates(self, request, pk=None):
        from accounts.services.merge import find_offline_duplicates

        company = self.get_object()
        duplicates = find_offline_duplicates(company).values("id", "name", "stated_inn", "is_registered")
        return Response(list(duplicates))

    @extend_schema(
        summary="Merge a duplicate offline company into this one",
        description="Platform Admin: fold an OFFLINE duplicate (its contacts, deals, activity, "
        "relationship edges) into this surviving company (CRM Phase C). Body: {duplicate_id, reason?}.",
        request={
            "application/json": {
                "type": "object",
                "properties": {"duplicate_id": {"type": "integer"}, "reason": {"type": "string"}},
                "required": ["duplicate_id"],
            }
        },
        responses={200: OpenApiResponse(description="{merged: true}"), 400: OpenApiResponse(description="error code")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], permission_classes=[IsPlatformAdmin])
    def merge(self, request, pk=None):
        from accounts.services.merge import merge_companies

        survivor = self.get_object()
        try:
            duplicate_id = int(request.data.get("duplicate_id"))
        except (TypeError, ValueError):
            return Response({"detail": "DUPLICATE_ID_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        duplicate = Company.objects.filter(pk=duplicate_id).first()
        if duplicate is None:
            return Response({"detail": "COMPANY_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        _survivor, error = merge_companies(
            survivor, duplicate, actor=request.user, reason=(request.data.get("reason") or "").strip()
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"merged": True})

    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-verify-kyc",
        permission_classes=[permissions.IsAuthenticated, IsPlatformAdmin],
    )
    def bulk_verify_kyc(self, request):
        ids = request.data.get("ids") or []
        level = request.data.get("level") or VerificationStatusCode.L2_VERIFIED
        reason = (request.data.get("reason") or "").strip()
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "ids (non-empty list) is required"}, status=status.HTTP_400_BAD_REQUEST)
        companies = Company.objects.filter(id__in=ids)
        approved, skipped = services.bulk_verify_kyc(
            companies,
            request.user,
            level_code=level,
            reason=reason,
        )
        return Response({"approved": approved, "skipped": skipped})
