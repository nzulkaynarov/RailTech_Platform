from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import exceptions, filters, permissions
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts import services
from accounts.constants import SELLER_COMPANY_TYPES, VerificationStatusCode, WorkspaceRoleCode
from accounts.models import Company, CompanyMember, CustomUser
from accounts.serializers import (
    CompanyDocumentProfileSerializer,
    CompanySerializer,
    CompanySettingsSerializer,
    KYCDocumentSerializer,
    KYCVerificationSerializer,
    UserSerializer,
)
from accounts.services.permissions import member_has_permission
from core.permissions import IsPlatformAdmin, OperatorScoped


@extend_schema_view(
    list=extend_schema(
        summary="List companies",
        description="Returns all companies with KYC documents and members. Manager/Admin only.",
        tags=["Accounts"],
    ),
    create=extend_schema(
        summary="Create company",
        description="Register a new company. Manager/Admin only.",
        tags=["Accounts"],
    ),
    retrieve=extend_schema(
        summary="Get company details",
        description="Returns company details. Staff sees any company; members see only their own.",
        tags=["Accounts"],
    ),
    update=extend_schema(
        summary="Update company",
        description="Full update of company data (PUT). Manager/Admin only.",
        tags=["Accounts"],
    ),
    partial_update=extend_schema(
        summary="Partially update company",
        description="Partial update of company data (PATCH). Manager/Admin only.",
        tags=["Accounts"],
    ),
    destroy=extend_schema(
        summary="Delete company",
        description="Delete a company. Manager/Admin only.",
        tags=["Accounts"],
    ),
)
class CompanyViewSet(viewsets.ModelViewSet):
    """
    CRUD operations for companies.

    Includes KYC verification, document upload, team management, and member invitations.
    """

    queryset = (
        Company.objects.select_related("verification_status", "country")
        .prefetch_related(
            "kyc_documents__doc_type",
            "types",
            "members",
        )
        .order_by("-created_at")
    )
    serializer_class = CompanySerializer
    permission_classes = [permissions.IsAuthenticated, OperatorScoped]
    # Operator sub-capability per admin-only action (ADR-0004 G1). Member-facing actions
    # (see _MEMBER_ALLOWED_ACTIONS) bypass this via get_permissions; unmapped admin actions
    # fall back to the coarse platform-operator gate.
    operator_permissions = {
        "list": "companies.view",
        "retrieve": "companies.view",
        "export": "companies.view",
        "create": "companies.manage",
        "update": "companies.manage",
        "partial_update": "companies.manage",
        "destroy": "companies.manage",
        "verify_kyc": "kyc.verify",
        "bulk_verify_kyc": "kyc.verify",
    }
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = {
        "verification_status__code": ["exact"],
        "types__code": ["exact"],
    }
    search_fields = ["name", "inn", "mfo", "contact_person", "email"]

    # Actions that a company member may perform on their own company
    # (logo upload, KYC document upload/delete, partial update of profile fields).
    # Actions a company MEMBER (not just a platform admin) may reach — the class is
    # otherwise IsPlatformAdmin. invite / update_member_capabilities enforce OWNER
    # inside the action itself, so IsAuthenticated here is correct (without this the
    # OWNER's own team-management is blocked with "platform administrators only").
    _MEMBER_ALLOWED_ACTIONS = {
        "retrieve",
        "update",
        "partial_update",
        "upload_document",
        "delete_document",
        "download_document",
        "upload_logo",
        "delete_logo",
        "document_profile",
        "upload_document_profile_logo",
        "company_settings",
        "team",
        "invite",
        "update_member_capabilities",
        "set_member_role",
    }

    def get_permissions(self):
        # Member-facing actions (own-company self-service / OWNER team management) carry their
        # own in-action authz and must NOT hit the operator gate — BUT only for non-operators.
        # A platform OPERATOR calling these still goes through OperatorScoped so a narrow role
        # (e.g. SUPPORT) cannot edit company data via update/partial_update (escalation fix).
        if self.action in self._MEMBER_ALLOWED_ACTIONS and not getattr(self.request.user, "is_platform_admin", False):
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    @extend_schema(
        summary="List verified suppliers (for RFQ invitations)",
        description=(
            "Minimal directory of verified SUPPLIER / MANUFACTURER companies a buyer "
            "can invite to an RFQ. Available to any authenticated member — returns only "
            "id, name and INN, NOT the full admin company record (no KYC internals)."
        ),
        responses={200: OpenApiResponse(description="List of {id, name, inn}")},
        tags=["Accounts"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="suppliers",
        permission_classes=[permissions.IsAuthenticated],
        pagination_class=None,
    )
    def suppliers(self, request):
        """Buyer-facing supplier directory for the open-RFQ invite flow.

        Deliberately narrow (id/name/inn) and capped to verified sellers, so the
        full company list — protected by IsPlatformAdmin — stays admin-only.
        """
        verified_suppliers = (
            Company.objects.filter(
                types__code__in=SELLER_COMPANY_TYPES,
                verification_status__code=VerificationStatusCode.L2_VERIFIED,
            )
            .distinct()
            .order_by("name")
            .values("id", "name", "inn")
        )
        return Response(list(verified_suppliers))

    def _assert_member_or_admin(self, company):
        user = self.request.user
        if user.is_platform_admin:
            return
        if not CompanyMember.objects.filter(
            user=user,
            company=company,
            is_active=True,
        ).exists():
            raise exceptions.PermissionDenied("ONLY_COMPANY_MEMBER_OR_ADMIN")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if not request.user.is_platform_admin:
            # Check if user is a member of this company
            membership = CompanyMember.objects.filter(user=request.user, company=instance).exists()
            if not membership:
                raise exceptions.PermissionDenied("You can only view your own company.")
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def _assert_owner_or_admin(self, company):
        """Editing the company profile is an OWNER action (or platform admin).
        Plain members may view but not change company data. The serializer's
        read_only_fields still protect KYC verdicts (verification_status /
        is_verified / trust_score) from any non-admin write."""
        user = self.request.user
        if user.is_platform_admin:
            return
        is_owner = CompanyMember.objects.filter(
            user=user,
            company=company,
            is_active=True,
            role__code=WorkspaceRoleCode.OWNER,
        ).exists()
        if not is_owner:
            raise exceptions.PermissionDenied("ONLY_COMPANY_OWNER_OR_ADMIN")

    def update(self, request, *args, **kwargs):
        self._assert_owner_or_admin(self.get_object())
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._assert_owner_or_admin(self.get_object())
        return super().partial_update(request, *args, **kwargs)

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

    @extend_schema(
        summary="Bulk verify KYC",
        description="Platform Admin: verify KYC for multiple companies in one request.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "integer"}},
                    "level": {"type": "string", "default": "L2_VERIFIED"},
                    "reason": {"type": "string"},
                },
                "required": ["ids"],
            }
        },
        responses={200: OpenApiResponse(description="approved count + skipped")},
        tags=["Accounts"],
    )
    @extend_schema(
        summary="Export companies",
        description="Export filtered companies list as CSV or XLSX (format=csv|xlsx).",
        tags=["Accounts"],
    )
    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        from core.exporters import export_queryset

        qs = self.filter_queryset(self.get_queryset())

        def _types(c):
            return ",".join(sorted(t.code for t in c.types.all()))

        return export_queryset(
            qs,
            request=request,
            filename="companies",
            columns=[
                ("id", "ID", lambda c: c.id),
                ("name", "Name", lambda c: c.name),
                ("inn", "INN", lambda c: c.inn or ""),
                ("verification", "KYC", lambda c: c.verification_status.code if c.verification_status_id else ""),
                ("types", "Types", _types),
                ("email", "Email", lambda c: c.email or ""),
                ("phone", "Phone", lambda c: c.phone or ""),
                ("contact_person", "Contact", lambda c: c.contact_person or ""),
                ("created_at", "Created", lambda c: c.created_at.isoformat() if c.created_at else ""),
            ],
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-verify-kyc",
        permission_classes=[permissions.IsAuthenticated, OperatorScoped],
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

    @extend_schema(
        summary="Upload KYC document",
        description="Upload a KYC document for company verification. Supports multipart file upload.",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "doc_type": {"type": "string", "default": "OTHER"},
                },
            }
        },
        responses={201: KYCDocumentSerializer},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="upload-document", parser_classes=[MultiPartParser, FormParser])
    def upload_document(self, request, pk=None):
        company = self.get_object()
        self._assert_member_or_admin(company)
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "NO_FILE_PROVIDED"}, status=status.HTTP_400_BAD_REQUEST)

        doc_type_code = request.data.get("doc_type", "OTHER")
        doc, error = services.upload_kyc_document(company, file_obj, doc_type_code)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(KYCDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Delete KYC document",
        description="Delete a specific KYC document by its ID from a company.",
        responses={204: None, 404: OpenApiResponse(description="Document not found")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["delete"], url_path="delete-document/(?P<doc_id>[0-9]+)", url_name="delete-document")
    def delete_document(self, request, pk=None, doc_id=None):
        company = self.get_object()
        self._assert_member_or_admin(company)
        success, error = services.delete_kyc_document(company, int(doc_id))
        if error:
            return Response({"detail": error}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Download a KYC document",
        description="Stream a KYC document for review. Works with both MinIO and local storage "
        "(prod has no MinIO, so the raw /media URL 404s — this authenticated stream is the only path).",
        responses={200: OpenApiResponse(description="File stream"), 404: OpenApiResponse(description="Not found")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["get"], url_path="download-document/(?P<doc_id>[0-9]+)", url_name="download-document")
    def download_document(self, request, pk=None, doc_id=None):
        from core.file_streaming import stream_file_field

        company = self.get_object()
        self._assert_member_or_admin(company)
        doc = company.kyc_documents.filter(id=int(doc_id)).first()
        if not doc:
            return Response({"detail": "DOCUMENT_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        return stream_file_field(doc.file, content_type="application/octet-stream")

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
        responses={200: CompanySerializer},
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
            403: OpenApiResponse(description="Only the company OWNER may read/update the profile"),
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
        summary="Upload company document-profile logo",
        description="Upload or replace the logo printed in the КП / contract header (multipart/form-data). OWNER only.",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {"logo": {"type": "string", "format": "binary"}},
            }
        },
        responses={200: CompanyDocumentProfileSerializer},
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
            "master-data CODES (e.g. 'USD', 'FCA'). OWNER of THIS company (or platform admin) only."
        ),
        request=CompanySettingsSerializer,
        responses={
            200: CompanySettingsSerializer,
            403: OpenApiResponse(description="Only the company OWNER may read/update the settings"),
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

    @extend_schema(
        summary="Get company team members",
        description="Returns all users that are members of this company. Accessible by team members and staff.",
        responses={200: UserSerializer(many=True)},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["get"])
    def team(self, request, pk=None):
        company = self.get_object()
        is_member = CompanyMember.objects.filter(user=request.user, company=company).exists()
        if not (is_member or request.user.is_platform_admin):
            raise exceptions.PermissionDenied("You can only view your own team.")

        # UserSerializer renders nested memberships + primary_company + types; without
        # prefetching this is a severe N+1 (one extra query per member per relation),
        # which over Neon's cross-region latency made this endpoint take ~23s and hang
        # the team UI. Mirror the /me prefetch so it's a handful of queries total.
        users = (
            CustomUser.objects.filter(memberships__company=company)
            .select_related("role")
            .prefetch_related(
                Prefetch(
                    "memberships",
                    queryset=CompanyMember.objects.select_related(
                        "company__verification_status",
                        "company__country",
                        "role",
                        "company_role",
                    ).prefetch_related("company__types"),
                ),
            )
            .distinct()
        )
        return Response(UserSerializer(users, many=True, context={"request": request}).data)

    @extend_schema(
        summary="Update member capabilities (sell / buy flags)",
        description=(
            "Company OWNER distributes selling / buying rights across team members. "
            "Only OWNER of the same company (or platform ADMIN/superuser) may call this."
        ),
        request=inline_serializer(
            "MemberCapabilities",
            fields={
                "member_id": drf_serializers.IntegerField(),
                "can_sell": drf_serializers.BooleanField(required=False),
                "can_buy": drf_serializers.BooleanField(required=False),
            },
        ),
        responses={
            200: OpenApiResponse(description="Capabilities updated"),
            403: OpenApiResponse(description="Only OWNER can distribute rights"),
            404: OpenApiResponse(description="Member not found in this company"),
        },
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="update-member-capabilities")
    def update_member_capabilities(self, request, pk=None):
        company = self.get_object()
        # Authorization (ADR-0005 U2): the team.manage CompanyRole permission (OWNER holds it via
        # the is_system role), or platform staff/superuser. Lets a delegated company admin manage
        # the team, not only the founding OWNER.
        is_staff = request.user.is_platform_admin
        if not is_staff and not member_has_permission(request.user, company.id, "team.manage"):
            return Response({"detail": "ONLY_OWNER_CAN_DISTRIBUTE_CAPABILITIES"}, status=status.HTTP_403_FORBIDDEN)

        member_id = request.data.get("member_id")
        if not member_id:
            return Response({"detail": "MEMBER_ID_REQUIRED"}, status=400)
        member = CompanyMember.objects.filter(pk=member_id, company=company).first()
        if not member:
            return Response({"detail": "MEMBER_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        changed = []
        if "can_sell" in request.data:
            member.can_sell = bool(request.data["can_sell"])
            changed.append("can_sell")
        if "can_buy" in request.data:
            member.can_buy = bool(request.data["can_buy"])
            changed.append("can_buy")
        if changed:
            member.save(update_fields=[*changed, "joined_at"][: len(changed)])
        return Response(
            {
                "id": member.id,
                "user_id": member.user_id,
                "can_sell": member.can_sell,
                "can_buy": member.can_buy,
            }
        )

    @extend_schema(
        summary="Set a member's workspace role",
        description=(
            "Company Admin (OWNER) delegates / changes a member's workspace role. "
            "Refuses to demote the last admin (never-orphan)."
        ),
        request=inline_serializer(
            "SetMemberRole",
            fields={
                "member_id": drf_serializers.IntegerField(),
                "role": drf_serializers.CharField(),
            },
        ),
        responses={
            200: OpenApiResponse(description="Role updated"),
            403: OpenApiResponse(description="Only Company Admin can change roles"),
            404: OpenApiResponse(description="Member not found"),
            409: OpenApiResponse(description="Cannot demote the last admin"),
        },
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="set-member-role")
    def set_member_role(self, request, pk=None):
        company = self.get_object()
        # Authorization: Company Admin (OWNER) of this company, or platform staff.
        if not request.user.is_platform_admin:
            is_admin = CompanyMember.objects.filter(
                user=request.user, company=company, is_active=True, role__code=WorkspaceRoleCode.OWNER
            ).exists()
            if not is_admin:
                return Response({"detail": "ONLY_COMPANY_ADMIN_CAN_CHANGE_ROLES"}, status=status.HTTP_403_FORBIDDEN)

        member_id = request.data.get("member_id")
        role_code = request.data.get("role")
        if not member_id or not role_code:
            return Response({"detail": "MEMBER_ID_AND_ROLE_REQUIRED"}, status=400)
        member = CompanyMember.objects.filter(pk=member_id, company=company).select_related("role").first()
        if not member:
            return Response({"detail": "MEMBER_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        result, error = services.set_member_workspace_role(member, role_code)
        if error:
            http_status = (
                status.HTTP_409_CONFLICT if error == "CANNOT_DEMOTE_LAST_COMPANY_ADMIN" else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": error}, status=http_status)
        return Response({"id": result.id, "user_id": result.user_id, "role": result.role.code})

    @extend_schema(
        summary="Invite team member",
        description=(
            "Invite a new user to the company by email. "
            "Only the company owner or staff can invite. Default role: PROCUREMENT_MANAGER."
        ),
        request=inline_serializer(
            "InviteRequest",
            fields={
                "email": drf_serializers.EmailField(),
                "role": drf_serializers.CharField(default="PROCUREMENT_MANAGER"),
            },
        ),
        responses={
            201: UserSerializer,
            400: OpenApiResponse(description="Invalid email or role"),
            403: OpenApiResponse(description="Not authorized"),
        },
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"])
    def invite(self, request, pk=None):
        """Invite a new team member to the company."""
        company = self.get_object()

        # Inviting a member is team management → the team.manage permission (OWNER holds it via
        # the is_system role; a delegated company admin too), or platform staff (ADR-0005 U2).
        if not request.user.is_platform_admin and not member_has_permission(request.user, company.id, "team.manage"):
            return Response({"detail": "ONLY_COMPANY_OWNER_CAN_INVITE"}, status=status.HTTP_403_FORBIDDEN)

        email = request.data.get("email")
        role_code = request.data.get("role", "PROCUREMENT_MANAGER")

        from accounts.services import invite_workspace_member

        user, error = invite_workspace_member(company, email, role_code)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
