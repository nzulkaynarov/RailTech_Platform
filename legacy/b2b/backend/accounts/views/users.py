from django.db.models import Prefetch
from django.utils.translation import gettext_lazy as _
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
from accounts.serializers import SelfUpdateSerializer, UserSerializer
from core.permissions import OperatorScoped


@extend_schema_view(
    list=extend_schema(summary="List users", description="Returns all users. Admin only.", tags=["Accounts"]),
    create=extend_schema(summary="Create user", description="Create a new user. Admin only.", tags=["Accounts"]),
    retrieve=extend_schema(
        summary="Get user details", description="Returns user details with memberships. Admin only.", tags=["Accounts"]
    ),
    update=extend_schema(summary="Update user", description="Full update of user data. Admin only.", tags=["Accounts"]),
    partial_update=extend_schema(
        summary="Partially update user", description="Partial update of user data. Admin only.", tags=["Accounts"]
    ),
    destroy=extend_schema(summary="Delete user", description="Delete a user. Admin only.", tags=["Accounts"]),
)
class UserViewSet(viewsets.ModelViewSet):
    """
    CRUD operations for users (Admin only).

    Includes password change, profile update, and user activation/deactivation.
    """

    queryset = (
        CustomUser.objects.all()
        .select_related("role")
        .prefetch_related(
            Prefetch(
                "memberships",
                queryset=CompanyMember.objects.select_related(
                    "company__verification_status",
                    "company__country",
                    "role",
                ).prefetch_related(
                    "company__kyc_documents__doc_type",
                    "company__types",
                    "company__members",
                ),
            ),
        )
        .order_by("-date_joined")
    )
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, OperatorScoped]
    # Operator sub-capability per action (ADR-0004 G1). Self-service actions
    # (change-password, update-me, upload/delete-avatar, me) carry their own
    # IsAuthenticated permission_classes and bypass this map.
    operator_permissions = {
        "list": "users.view",
        "retrieve": "users.view",
        "export": "users.view",
        "create": "users.manage",
        "update": "users.manage",
        "partial_update": "users.manage",
        "destroy": "users.manage",
        "toggle_active": "users.manage",
        "change_role": "users.manage",
        "add_membership": "users.manage",
        "remove_membership": "users.manage",
    }
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["is_active", "role__code"]
    search_fields = ["email", "first_name", "last_name", "phone"]

    @extend_schema(
        summary="Export users",
        description="Export filtered users list as CSV or XLSX.",
        tags=["Accounts"],
    )
    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        from core.exporters import export_queryset

        qs = self.filter_queryset(self.get_queryset())
        return export_queryset(
            qs,
            request=request,
            filename="users",
            columns=[
                ("id", "ID", lambda u: u.id),
                ("email", "Email", lambda u: u.email),
                ("first_name", "First name", lambda u: u.first_name or ""),
                ("last_name", "Last name", lambda u: u.last_name or ""),
                ("role", "Role", lambda u: u.role.code if u.role_id else ""),
                ("is_active", "Active", lambda u: u.is_active),
                ("last_login", "Last login", lambda u: u.last_login.isoformat() if u.last_login else ""),
                ("date_joined", "Joined", lambda u: u.date_joined.isoformat() if u.date_joined else ""),
            ],
        )

    @extend_schema(
        summary="Change password",
        description="Change the current user's password. Requires current password for verification.",
        request=inline_serializer(
            "ChangePasswordRequest",
            fields={
                "current_password": drf_serializers.CharField(),
                "new_password": drf_serializers.CharField(min_length=8),
            },
        ),
        responses={
            200: OpenApiResponse(description="Password changed"),
            400: OpenApiResponse(description="Invalid current password"),
        },
        tags=["Accounts"],
    )
    @action(
        detail=False, methods=["post"], url_path="change-password", permission_classes=[permissions.IsAuthenticated]
    )
    def change_password(self, request):
        from accounts.serializers import ChangePasswordSerializer

        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        __, error = services.change_user_password(
            request.user,
            serializer.validated_data["current_password"],
            serializer.validated_data["new_password"],
        )
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": str(_("Password changed successfully"))})

    @extend_schema(
        summary="Update current user profile",
        description="Partial update of the authenticated user's own profile.",
        request=SelfUpdateSerializer,
        responses={200: SelfUpdateSerializer},
        tags=["Accounts"],
    )
    @action(detail=False, methods=["patch"], url_path="update-me", permission_classes=[permissions.IsAuthenticated])
    def update_me(self, request):
        # SelfUpdateSerializer (not the admin UserSerializer): a user may edit only
        # their own name/phone/position/avatar — never email/username/is_active/role.
        serializer = SelfUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @extend_schema(
        summary="Upload user avatar",
        description="Upload or replace the authenticated user's avatar (multipart/form-data).",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "avatar": {"type": "string", "format": "binary"},
                },
            }
        },
        responses={200: UserSerializer},
        tags=["Accounts"],
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="upload-avatar",
        permission_classes=[permissions.IsAuthenticated],
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_avatar(self, request):
        avatar = request.FILES.get("avatar")
        if not avatar:
            return Response({"detail": "NO_FILE_PROVIDED"}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.exceptions import ValidationError

        from core.validators import validate_avatar_upload

        try:
            validate_avatar_upload(avatar)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        if user.avatar:
            user.avatar.delete(save=False)
        user.avatar = avatar
        user.save(update_fields=["avatar"])
        return Response(UserSerializer(user, context={"request": request}).data)

    @extend_schema(
        summary="Delete user avatar",
        responses={204: None},
        tags=["Accounts"],
    )
    @action(
        detail=False,
        methods=["delete"],
        url_path="delete-avatar",
        permission_classes=[permissions.IsAuthenticated],
    )
    def delete_avatar(self, request):
        user = request.user
        if user.avatar:
            user.avatar.delete(save=False)
            user.avatar = None
            user.save(update_fields=["avatar"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Upload avatar for a user (admin or self)",
        description="Platform admin may set avatar on behalf of any user; users may set their own.",
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "avatar": {"type": "string", "format": "binary"},
                },
            }
        },
        responses={200: UserSerializer},
        tags=["Accounts"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="upload-avatar",
        permission_classes=[permissions.IsAuthenticated],
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_avatar_for(self, request, pk=None):
        target = self.get_object()
        if not (request.user.is_platform_admin or request.user.pk == target.pk):
            raise exceptions.PermissionDenied("ONLY_ADMIN_OR_SELF_CAN_SET_AVATAR")
        avatar = request.FILES.get("avatar")
        if not avatar:
            return Response({"detail": "NO_FILE_PROVIDED"}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.exceptions import ValidationError

        from core.validators import validate_avatar_upload

        # SEC-08: same extension/content-type/size/magic-byte guard the self-service
        # upload_avatar already enforces — this admin path stored the file unchecked.
        try:
            validate_avatar_upload(avatar)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if target.avatar:
            target.avatar.delete(save=False)
        target.avatar = avatar
        target.save(update_fields=["avatar"])
        return Response(UserSerializer(target, context={"request": request}).data)

    @extend_schema(
        summary="Delete avatar for a user (admin or self)",
        responses={204: None},
        tags=["Accounts"],
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path="delete-avatar",
        permission_classes=[permissions.IsAuthenticated],
    )
    def delete_avatar_for(self, request, pk=None):
        target = self.get_object()
        if not (request.user.is_platform_admin or request.user.pk == target.pk):
            raise exceptions.PermissionDenied("ONLY_ADMIN_OR_SELF_CAN_DELETE_AVATAR")
        if target.avatar:
            target.avatar.delete(save=False)
            target.avatar = None
            target.save(update_fields=["avatar"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Get current user (via users endpoint)",
        description="Returns the authenticated user's profile via the users ViewSet.",
        responses={200: UserSerializer},
        tags=["Accounts"],
    )
    @action(detail=False, methods=["get"], url_path="me", permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        from accounts.serializers import MeSerializer

        user = (
            CustomUser.objects.select_related("role")
            .prefetch_related(
                Prefetch(
                    "memberships",
                    queryset=CompanyMember.objects.select_related(
                        "company__verification_status",
                        "company__country",
                        "role",
                        "company_role",  # capabilities.permissions reads the member's CompanyRole
                    ).prefetch_related("company__types"),
                ),
            )
            .filter(pk=request.user.pk)
            .first()
            or request.user
        )
        return Response(MeSerializer(user, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Toggle user active status",
        description="Activate or deactivate a user. Admin only.",
        responses={200: OpenApiResponse(description="User status toggled")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="toggle-active")
    def toggle_active(self, request, pk=None):
        user = self.get_object()
        result, error = services.toggle_user_active(user, request.user)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "status": "activated" if result.is_active else "deactivated",
                "is_active": result.is_active,
            }
        )

    @extend_schema(
        summary="Change user role",
        description="Change the system role of a user. Admin only.",
        request=inline_serializer(
            "ChangeRoleRequest",
            {
                "role": drf_serializers.CharField(),
            },
        ),
        responses={200: OpenApiResponse(description="Role updated")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="change-role")
    def change_role(self, request, pk=None):
        user = self.get_object()
        role_code = request.data.get("role")
        result, error = services.change_user_role(user, role_code)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(UserSerializer(result).data)

    @extend_schema(
        summary="Add user to company (workspace membership)",
        description="Platform Admin creates a CompanyMember link for the target user.",
        request=inline_serializer(
            "AddMembershipRequest",
            {
                "company": drf_serializers.IntegerField(),
                "workspace_role": drf_serializers.CharField(),
                "is_primary": drf_serializers.BooleanField(required=False, default=False),
            },
        ),
        responses={
            201: OpenApiResponse(description="Membership created"),
            400: OpenApiResponse(description="Validation error (see error_code)"),
            404: OpenApiResponse(description="Company not found"),
        },
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="add-membership")
    def add_membership(self, request, pk=None):
        user = self.get_object()
        company_id = request.data.get("company")
        workspace_role_code = request.data.get("workspace_role")
        is_primary = bool(request.data.get("is_primary", False))
        if not company_id or not workspace_role_code:
            return Response({"detail": "COMPANY_AND_WORKSPACE_ROLE_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        company = Company.objects.filter(pk=company_id).first()
        if not company:
            return Response({"detail": "COMPANY_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        membership, error = services.add_company_member(
            user,
            company,
            workspace_role_code,
            is_primary=is_primary,
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "id": membership.id,
                "company_id": company.id,
                "company_name": company.name,
                "workspace_role": membership.role.code,
                "is_primary": membership.is_primary,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Remove workspace membership",
        description="Delete a CompanyMember link.",
        responses={204: None, 404: OpenApiResponse(description="Membership not found")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["delete"], url_path="remove-membership/(?P<membership_id>[0-9]+)")
    def remove_membership(self, request, pk=None, membership_id=None):
        user = self.get_object()
        membership = CompanyMember.objects.filter(pk=membership_id, user=user).select_related("company", "role").first()
        if not membership:
            return Response({"detail": "MEMBERSHIP_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        # Never-orphan invariant lives in the service (Rule 8).
        _result, error = services.remove_company_member(membership)
        if error:
            return Response({"detail": error}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)
