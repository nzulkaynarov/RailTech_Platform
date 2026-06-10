from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import exceptions, filters, permissions
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts import services
from accounts.models import Company, CompanyMember, CustomUser
from accounts.serializers import CompanySerializer, KYCDocumentSerializer, KYCVerificationSerializer, UserSerializer
from core.permissions import IsPlatformAdmin


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
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = {
        "verification_status__code": ["exact"],
        "types__code": ["exact"],
    }
    search_fields = ["name", "inn", "mfo", "contact_person", "email"]

    # Actions that a company member may perform on their own company
    # (logo upload, KYC document upload/delete, partial update of profile fields).
    _MEMBER_ALLOWED_ACTIONS = {
        "retrieve",
        "update",
        "partial_update",
        "upload_document",
        "delete_document",
        "upload_logo",
        "delete_logo",
        "team",
    }

    def get_permissions(self):
        if self.action in self._MEMBER_ALLOWED_ACTIONS:
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
                types__code__in=["SUPPLIER", "MANUFACTURER"],
                verification_status__code="L2_VERIFIED",
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
            role__code="OWNER",
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
                return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

            if comment:
                result.kyc_notes = comment
                result.save(update_fields=["kyc_notes"])

            return Response({"status": "Status updated", "new_status": result.verification_status.name})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
        permission_classes=[permissions.IsAuthenticated, IsPlatformAdmin],
    )
    def bulk_verify_kyc(self, request):
        ids = request.data.get("ids") or []
        level = request.data.get("level") or "L2_VERIFIED"
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
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
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

        users = CustomUser.objects.filter(memberships__company=company).distinct()
        return Response(UserSerializer(users, many=True).data)

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
        # Authorization: OWNER of this company, or platform staff/superuser.
        is_staff = request.user.is_platform_admin
        if not is_staff:
            owner_membership = CompanyMember.objects.filter(
                user=request.user,
                company=company,
                is_active=True,
                role__code="OWNER",
            ).exists()
            if not owner_membership:
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

        # Only company owner can invite
        membership = (
            CompanyMember.objects.filter(user=request.user, company=company, is_active=True)
            .select_related("role")
            .first()
        )

        if not membership or membership.role.code != "OWNER":
            is_staff = request.user.is_platform_admin
            if not is_staff:
                return Response({"detail": "ONLY_COMPANY_OWNER_CAN_INVITE"}, status=status.HTTP_403_FORBIDDEN)

        email = request.data.get("email")
        role_code = request.data.get("role", "PROCUREMENT_MANAGER")

        from accounts.services import invite_workspace_member

        user, error = invite_workspace_member(company, email, role_code)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
