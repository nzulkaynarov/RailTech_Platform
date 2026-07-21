"""Team / membership actions for ``CompanyViewSet``.

Split out of the monolithic ``accounts/views/company.py`` (file-length refactor,
500-line rule) as a mixin — behaviour, ``url_path``/``url_name`` and permissions
are unchanged. Mixed into ``CompanyViewSet``, which supplies ``get_object``; this
class only adds ``@action`` methods. Team-management authz (``member_has_permission``
'team.manage', never-orphan) lives in the actions / services exactly as before.
"""

from django.db.models import Prefetch
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import exceptions
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts import services
from accounts.models import CompanyMember, CustomUser
from accounts.serializers import UserSerializer
from accounts.services.permissions import member_has_permission


class CompanyTeamMixin:
    """Team-listing and membership-management ``@action`` endpoints."""

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
        # Authorization (ADR-0005 Phase E U3): team.manage CompanyRole permission, or platform
        # staff. Mirrors update_member_capabilities / invite (member_has_permission 'team.manage').
        # The is_platform_admin bypass stays — member_has_permission is True for a superuser but
        # NOT for a non-superuser platform operator.
        if not request.user.is_platform_admin and not member_has_permission(request.user, company.id, "team.manage"):
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
