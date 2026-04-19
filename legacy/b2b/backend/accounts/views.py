from rest_framework import viewsets, status, views, permissions, exceptions, filters, serializers as drf_serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.generics import RetrieveAPIView
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse, inline_serializer

from django.db.models import Prefetch
from django.utils.translation import gettext_lazy as _

from core.permissions import IsPlatformAdmin

from . import services
from .models import (
    Company, CompanyMember, CompanyRoleApplication, CustomUser,
    SupplierSubscription, SystemRole, WorkspaceRole,
)
from .services import (
    create_pending_user, verify_and_setup_password,
    submit_company_profile,
)
from .serializers import (
    CompanyRoleApplicationSerializer, CompanySerializer,
    KYCDocumentSerializer, KYCVerificationSerializer,
    RegisterInterestSerializer, SetupPasswordSerializer,
    SubmitProfileSerializer, SupplierSubscriptionSerializer,
    UserSerializer,
)


@extend_schema_view(
    list=extend_schema(
        summary="List companies",
        description="Returns all companies with KYC documents and members. Manager/Admin only.",
        tags=['Accounts'],
    ),
    create=extend_schema(
        summary="Create company",
        description="Register a new company. Manager/Admin only.",
        tags=['Accounts'],
    ),
    retrieve=extend_schema(
        summary="Get company details",
        description="Returns company details. Staff sees any company; members see only their own.",
        tags=['Accounts'],
    ),
    update=extend_schema(
        summary="Update company",
        description="Full update of company data (PUT). Manager/Admin only.",
        tags=['Accounts'],
    ),
    partial_update=extend_schema(
        summary="Partially update company",
        description="Partial update of company data (PATCH). Manager/Admin only.",
        tags=['Accounts'],
    ),
    destroy=extend_schema(
        summary="Delete company",
        description="Delete a company. Manager/Admin only.",
        tags=['Accounts'],
    ),
)
class CompanyViewSet(viewsets.ModelViewSet):
    """
    CRUD operations for companies.

    Includes KYC verification, document upload, team management, and member invitations.
    """
    queryset = Company.objects.select_related(
        'verification_status', 'country'
    ).prefetch_related(
        'kyc_documents__doc_type',
        'types',
        'members',
    ).order_by('-created_at')
    serializer_class = CompanySerializer
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = {
        'verification_status__code': ['exact'],
        'types__code': ['exact'],
    }
    search_fields = ['name', 'inn', 'mfo', 'contact_person', 'email']

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if not request.user.is_platform_admin:
            # Check if user is a member of this company
            membership = CompanyMember.objects.filter(user=request.user, company=instance).exists()
            if not membership:
                raise exceptions.PermissionDenied("You can only view your own company.")
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

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
        tags=['Accounts'],
    )
    @action(detail=True, methods=['post'], url_path='verify-kyc')
    def verify_kyc(self, request, pk=None):
        company = self.get_object()
        serializer = KYCVerificationSerializer(data=request.data)
        if serializer.is_valid():
            code = serializer.validated_data['status_code']
            comment = serializer.validated_data.get('comment', '')

            result, error = services.verify_company_kyc(
                company, request.user, level_code=code, require_documents=True
            )
            if error:
                return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

            if comment:
                result.kyc_notes = comment
                result.save(update_fields=['kyc_notes'])

            return Response({'status': 'Status updated', 'new_status': result.verification_status.name})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Upload KYC document",
        description="Upload a KYC document for company verification. Supports multipart file upload.",
        request={'multipart/form-data': {'type': 'object', 'properties': {
            'file': {'type': 'string', 'format': 'binary'},
            'doc_type': {'type': 'string', 'default': 'OTHER'},
        }}},
        responses={201: KYCDocumentSerializer},
        tags=['Accounts'],
    )
    @action(
        detail=True,
        methods=['post'],
        url_path='upload-document',
        parser_classes=[MultiPartParser, FormParser]
    )
    def upload_document(self, request, pk=None):
        company = self.get_object()
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'detail': 'NO_FILE_PROVIDED'}, status=status.HTTP_400_BAD_REQUEST)

        doc_type_code = request.data.get('doc_type', 'OTHER')
        doc, error = services.upload_kyc_document(company, file_obj, doc_type_code)
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(KYCDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Delete KYC document",
        description="Delete a specific KYC document by its ID from a company.",
        responses={204: None, 404: OpenApiResponse(description="Document not found")},
        tags=['Accounts'],
    )
    @action(detail=True, methods=['delete'], url_path='delete-document/(?P<doc_id>[0-9]+)', url_name='delete-document')
    def delete_document(self, request, pk=None, doc_id=None):
        company = self.get_object()
        success, error = services.delete_kyc_document(company, int(doc_id))
        if error:
            return Response({'detail': error}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Get company team members",
        description="Returns all users that are members of this company. Accessible by team members and staff.",
        responses={200: UserSerializer(many=True)},
        tags=['Accounts'],
    )
    @action(detail=True, methods=['get'])
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
        request=inline_serializer('MemberCapabilities', fields={
            'member_id': drf_serializers.IntegerField(),
            'can_sell': drf_serializers.BooleanField(required=False),
            'can_buy': drf_serializers.BooleanField(required=False),
        }),
        responses={
            200: OpenApiResponse(description="Capabilities updated"),
            403: OpenApiResponse(description="Only OWNER can distribute rights"),
            404: OpenApiResponse(description="Member not found in this company"),
        },
        tags=['Accounts'],
    )
    @action(detail=True, methods=['post'], url_path='update-member-capabilities')
    def update_member_capabilities(self, request, pk=None):
        company = self.get_object()
        # Authorization: OWNER of this company, or platform staff/superuser.
        is_staff = request.user.is_platform_admin
        if not is_staff:
            owner_membership = CompanyMember.objects.filter(
                user=request.user, company=company, is_active=True,
                role__code='OWNER',
            ).exists()
            if not owner_membership:
                return Response({'detail': 'ONLY_OWNER_CAN_DISTRIBUTE_CAPABILITIES'},
                                status=status.HTTP_403_FORBIDDEN)

        member_id = request.data.get('member_id')
        if not member_id:
            return Response({'detail': 'MEMBER_ID_REQUIRED'}, status=400)
        member = CompanyMember.objects.filter(pk=member_id, company=company).first()
        if not member:
            return Response({'detail': 'MEMBER_NOT_FOUND'},
                            status=status.HTTP_404_NOT_FOUND)

        changed = []
        if 'can_sell' in request.data:
            member.can_sell = bool(request.data['can_sell'])
            changed.append('can_sell')
        if 'can_buy' in request.data:
            member.can_buy = bool(request.data['can_buy'])
            changed.append('can_buy')
        if changed:
            member.save(update_fields=[*changed, 'joined_at'][: len(changed)])
        return Response({
            'id': member.id, 'user_id': member.user_id,
            'can_sell': member.can_sell, 'can_buy': member.can_buy,
        })

    @extend_schema(
        summary="Invite team member",
        description=(
            "Invite a new user to the company by email. "
            "Only the company owner or staff can invite. Default role: PROCUREMENT_MANAGER."
        ),
        request=inline_serializer('InviteRequest', fields={
            'email': drf_serializers.EmailField(),
            'role': drf_serializers.CharField(default='PROCUREMENT_MANAGER'),
        }),
        responses={201: UserSerializer, 400: OpenApiResponse(description="Invalid email or role"), 403: OpenApiResponse(description="Not authorized")},
        tags=['Accounts'],
    )
    @action(detail=True, methods=['post'])
    def invite(self, request, pk=None):
        """Invite a new team member to the company."""
        company = self.get_object()

        # Only company owner can invite
        membership = CompanyMember.objects.filter(
            user=request.user, company=company, is_active=True
        ).select_related('role').first()

        if not membership or membership.role.code != 'OWNER':
            is_staff = request.user.is_platform_admin
            if not is_staff:
                return Response({'detail': 'ONLY_COMPANY_OWNER_CAN_INVITE'},
                              status=status.HTTP_403_FORBIDDEN)

        email = request.data.get('email')
        role_code = request.data.get('role', 'PROCUREMENT_MANAGER')

        from .services import invite_workspace_member
        user, error = invite_workspace_member(company, email, role_code)
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(summary="List users", description="Returns all users. Admin only.", tags=['Accounts']),
    create=extend_schema(summary="Create user", description="Create a new user. Admin only.", tags=['Accounts']),
    retrieve=extend_schema(summary="Get user details", description="Returns user details with memberships. Admin only.", tags=['Accounts']),
    update=extend_schema(summary="Update user", description="Full update of user data. Admin only.", tags=['Accounts']),
    partial_update=extend_schema(summary="Partially update user", description="Partial update of user data. Admin only.", tags=['Accounts']),
    destroy=extend_schema(summary="Delete user", description="Delete a user. Admin only.", tags=['Accounts']),
)
class UserViewSet(viewsets.ModelViewSet):
    """
    CRUD operations for users (Admin only).

    Includes password change, profile update, and user activation/deactivation.
    """
    queryset = CustomUser.objects.all().select_related('role').prefetch_related(
        Prefetch(
            'memberships',
            queryset=CompanyMember.objects.select_related(
                'company__verification_status',
                'company__country',
                'role',
            ).prefetch_related(
                'company__kyc_documents__doc_type',
                'company__types',
                'company__members',
            ),
        ),
    ).order_by('-date_joined')
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]

    @extend_schema(
        summary="Change password",
        description="Change the current user's password. Requires current password for verification.",
        request=inline_serializer('ChangePasswordRequest', fields={
            'current_password': drf_serializers.CharField(),
            'new_password': drf_serializers.CharField(min_length=8),
        }),
        responses={200: OpenApiResponse(description="Password changed"), 400: OpenApiResponse(description="Invalid current password")},
        tags=['Accounts'],
    )
    @action(detail=False, methods=['post'], url_path='change-password',
            permission_classes=[permissions.IsAuthenticated])
    def change_password(self, request):
        from .serializers import ChangePasswordSerializer
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        _, error = services.change_user_password(
            request.user,
            serializer.validated_data['current_password'],
            serializer.validated_data['new_password'],
        )
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': str(_('Password changed successfully'))})

    @extend_schema(
        summary="Update current user profile",
        description="Partial update of the authenticated user's own profile.",
        request=UserSerializer,
        responses={200: UserSerializer},
        tags=['Accounts'],
    )
    @action(detail=False, methods=['patch'], url_path='update-me',
            permission_classes=[permissions.IsAuthenticated])
    def update_me(self, request):
        serializer = self.get_serializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @extend_schema(
        summary="Get current user (via users endpoint)",
        description="Returns the authenticated user's profile via the users ViewSet.",
        responses={200: UserSerializer},
        tags=['Accounts'],
    )
    @action(detail=False, methods=['get'], url_path='me',
            permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        from .serializers import MeSerializer
        user = CustomUser.objects.select_related('role').prefetch_related(
            Prefetch(
                'memberships',
                queryset=CompanyMember.objects.select_related(
                    'company__verification_status', 'company__country', 'role',
                ).prefetch_related('company__types'),
            ),
        ).filter(pk=request.user.pk).first() or request.user
        return Response(MeSerializer(user, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Toggle user active status",
        description="Activate or deactivate a user. Admin only.",
        responses={200: OpenApiResponse(description="User status toggled")},
        tags=['Accounts'],
    )
    @action(detail=True, methods=['post'], url_path='toggle-active')
    def toggle_active(self, request, pk=None):
        user = self.get_object()
        result, error = services.toggle_user_active(user, request.user)
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'status': 'activated' if result.is_active else 'deactivated',
            'is_active': result.is_active,
        })

    @extend_schema(
        summary="Change user role",
        description="Change the system role of a user. Admin only.",
        request=inline_serializer('ChangeRoleRequest', {
            'role': drf_serializers.CharField(),
        }),
        responses={200: OpenApiResponse(description="Role updated")},
        tags=['Accounts'],
    )
    @action(detail=True, methods=['post'], url_path='change-role')
    def change_role(self, request, pk=None):
        user = self.get_object()
        role_code = request.data.get('role')
        result, error = services.change_user_role(user, role_code)
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
        from .serializers import UserSerializer
        return Response(UserSerializer(result).data)

    @extend_schema(
        summary="Add user to company (workspace membership)",
        description="Platform Admin creates a CompanyMember link for the target user.",
        request=inline_serializer('AddMembershipRequest', {
            'company': drf_serializers.IntegerField(),
            'workspace_role': drf_serializers.CharField(),
            'is_primary': drf_serializers.BooleanField(required=False, default=False),
        }),
        responses={
            201: OpenApiResponse(description="Membership created"),
            400: OpenApiResponse(description="Validation error (see error_code)"),
            404: OpenApiResponse(description="Company not found"),
        },
        tags=['Accounts'],
    )
    @action(detail=True, methods=['post'], url_path='add-membership')
    def add_membership(self, request, pk=None):
        user = self.get_object()
        company_id = request.data.get('company')
        workspace_role_code = request.data.get('workspace_role')
        is_primary = bool(request.data.get('is_primary', False))
        if not company_id or not workspace_role_code:
            return Response({'detail': 'COMPANY_AND_WORKSPACE_ROLE_REQUIRED'},
                            status=status.HTTP_400_BAD_REQUEST)
        from .models import Company
        company = Company.objects.filter(pk=company_id).first()
        if not company:
            return Response({'detail': 'COMPANY_NOT_FOUND'},
                            status=status.HTTP_404_NOT_FOUND)
        membership, error = services.add_company_member(
            user, company, workspace_role_code, is_primary=is_primary,
        )
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'id': membership.id,
            'company_id': company.id,
            'company_name': company.name,
            'workspace_role': membership.role.code,
            'is_primary': membership.is_primary,
        }, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Remove workspace membership",
        description="Delete a CompanyMember link.",
        responses={204: None, 404: OpenApiResponse(description="Membership not found")},
        tags=['Accounts'],
    )
    @action(detail=True, methods=['delete'], url_path='remove-membership/(?P<membership_id>[0-9]+)')
    def remove_membership(self, request, pk=None, membership_id=None):
        user = self.get_object()
        from .models import CompanyMember
        membership = CompanyMember.objects.filter(pk=membership_id, user=user).first()
        if not membership:
            return Response({'detail': 'MEMBERSHIP_NOT_FOUND'},
                            status=status.HTTP_404_NOT_FOUND)
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    summary="Register new user",
    description=(
        "Register a new user by email. Creates an inactive user and sends "
        "a verification email with a password setup link."
    ),
    request=RegisterInterestSerializer,
    responses={
        201: OpenApiResponse(description="Verification email sent"),
        400: OpenApiResponse(description="Email already exists or validation error"),
    },
    tags=['Auth'],
)
class RegisterView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterInterestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = create_pending_user(
            email=serializer.validated_data['email'],
            first_name=serializer.validated_data['first_name'],
            last_name=serializer.validated_data['last_name']
        )
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "message": "Verification email sent.",
            "email": user.email
        }, status=status.HTTP_201_CREATED)


@extend_schema(
    summary="Setup password",
    description=(
        "Set a password for a newly registered user. Requires the uid and token "
        "from the verification email link. Activates the user account."
    ),
    request=SetupPasswordSerializer,
    responses={
        200: OpenApiResponse(description="Password set, user activated"),
        400: OpenApiResponse(description="Invalid or expired token"),
    },
    tags=['Auth'],
)
class SetupPasswordView(views.APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = SetupPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = verify_and_setup_password(
            uidb64=serializer.validated_data['uid'],
            token=serializer.validated_data['token'],
            password=serializer.validated_data['password']
        )
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "message": "Password setup successful.",
            "user": UserSerializer(user).data
        })


@extend_schema(
    summary="Submit company profile",
    description=(
        "Submit company profile after registration. Creates or links a Company "
        "by INN, assigns workspace role and company type."
    ),
    request=SubmitProfileSerializer,
    responses={
        200: OpenApiResponse(description="Profile submitted successfully"),
        400: OpenApiResponse(description="Validation error"),
    },
    tags=['Auth'],
)
class SubmitProfileView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SubmitProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, error = submit_company_profile(
            user=request.user,
            inn=serializer.validated_data['inn'],
            company_name=serializer.validated_data['companyName'],
            workspace_role_code=serializer.validated_data['role_code'],
            company_type_code=serializer.validated_data.get('company_type', 'CLIENT'),
        )
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "message": "Profile submitted successful.",
            "user": UserSerializer(user).data
        })


@extend_schema(
    summary="Get current user profile",
    description="Returns the authenticated user's full profile including memberships and company data.",
    responses={200: UserSerializer},
    tags=['Accounts'],
)
class MeView(RetrieveAPIView):
    """
    Retrieve the current authenticated user's profile.
    GET /api/v1/accounts/me/
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


# ──────────────────────────────────────────────────────────────────────────
# Phase 3: Admin-facing ViewSets (React Admin pages)
# ──────────────────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(summary="List system roles", tags=['Accounts']),
    retrieve=extend_schema(summary="Get system role", tags=['Accounts']),
)
class SystemRoleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SystemRole.objects.all().order_by('sort_order', 'name')
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        data = [{'code': r.code, 'name': r.name} for r in self.get_queryset()]
        return Response(data)


@extend_schema_view(
    list=extend_schema(summary="List workspace roles", tags=['Accounts']),
    retrieve=extend_schema(summary="Get workspace role", tags=['Accounts']),
)
class WorkspaceRoleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Workspace roles (роли внутри компании) с типовой привязкой.

    Query:
      ?company_type=CLIENT — вернуть только роли, применимые к компаниям типа CLIENT
                             (плюс универсальные роли без ограничения по типу).
    """
    queryset = WorkspaceRole.objects.filter(is_active=True).prefetch_related('applicable_to_types').order_by('sort_order', 'name')
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        company_type = request.query_params.get('company_type')
        data = []
        for r in qs:
            applicable = list(r.applicable_to_types.values_list('code', flat=True))
            if company_type and applicable and company_type not in applicable:
                continue
            data.append({
                'code': r.code,
                'name': r.name,
                'applicable_to_types': applicable,
            })
        return Response(data)


@extend_schema_view(
    list=extend_schema(summary="List subscriptions", description="Returns all supplier subscriptions. Filterable by plan, status, company.", tags=['Accounts']),
    create=extend_schema(summary="Create subscription", description="Create a new supplier subscription.", tags=['Accounts']),
    retrieve=extend_schema(summary="Get subscription details", tags=['Accounts']),
    update=extend_schema(summary="Update subscription", tags=['Accounts']),
    partial_update=extend_schema(summary="Partially update subscription", tags=['Accounts']),
    destroy=extend_schema(summary="Delete subscription", tags=['Accounts']),
)
class SupplierSubscriptionViewSet(viewsets.ModelViewSet):
    """
    CRUD + status actions for supplier subscriptions.
    Admin/Manager only.
    """
    serializer_class = SupplierSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]
    filterset_fields = ['plan', 'status', 'company']
    search_fields = ['company__name', 'company__inn']
    ordering = ['-created_at']

    def get_queryset(self):
        return (
            SupplierSubscription.objects
            .select_related('company', 'currency')
            .order_by('-created_at')
        )

    @extend_schema(
        summary="Activate subscription",
        description="Set subscription status to ACTIVE.",
        responses={200: SupplierSubscriptionSerializer},
        tags=['Accounts'],
    )
    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        """POST /api/v1/accounts/subscriptions/{id}/activate/"""
        sub = self.get_object()
        services.change_subscription_status(
            SupplierSubscription.objects.filter(pk=sub.pk), 'ACTIVE'
        )
        sub.refresh_from_db()
        return Response(self.get_serializer(sub).data)

    @extend_schema(
        summary="Suspend subscription",
        description="Set subscription status to SUSPENDED.",
        responses={200: SupplierSubscriptionSerializer},
        tags=['Accounts'],
    )
    @action(detail=True, methods=['post'], url_path='suspend')
    def suspend(self, request, pk=None):
        """POST /api/v1/accounts/subscriptions/{id}/suspend/"""
        sub = self.get_object()
        services.change_subscription_status(
            SupplierSubscription.objects.filter(pk=sub.pk), 'SUSPENDED'
        )
        sub.refresh_from_db()
        return Response(self.get_serializer(sub).data)

    @extend_schema(summary="Record subscription payment — extends validity and activates",
                   tags=['Accounts'])
    @action(detail=True, methods=['post'], url_path='pay',
            permission_classes=[permissions.IsAuthenticated])
    def pay(self, request, pk=None):
        sub = self.get_object()
        amount = request.data.get('amount', 0)
        months = int(request.data.get('months', 1))
        sub, error = services.record_subscription_payment(
            sub, amount, months=months, actor=request.user, manual=True,
        )
        if error:
            return Response({'error': error}, status=status.HTTP_403_FORBIDDEN)
        return Response(self.get_serializer(sub).data)


@extend_schema_view(
    list=extend_schema(summary="List role applications", description="Returns all company role applications. Filterable by status, type, company.", tags=['Accounts']),
    create=extend_schema(summary="Create role application", description="Submit a new role application for a company.", tags=['Accounts']),
    retrieve=extend_schema(summary="Get role application details", tags=['Accounts']),
    update=extend_schema(summary="Update role application", tags=['Accounts']),
    partial_update=extend_schema(summary="Partially update role application", tags=['Accounts']),
    destroy=extend_schema(summary="Delete role application", tags=['Accounts']),
)
class CompanyRoleApplicationViewSet(viewsets.ModelViewSet):
    """
    CRUD + approve/reject for company role applications.
    Admin/Manager only.
    """
    serializer_class = CompanyRoleApplicationSerializer
    permission_classes = [permissions.IsAuthenticated, IsPlatformAdmin]
    filterset_fields = ['status', 'requested_type', 'company']
    search_fields = ['company__name', 'company__inn']
    ordering = ['-created_at']

    def get_queryset(self):
        return (
            CompanyRoleApplication.objects
            .select_related('company', 'requested_type', 'submitted_by', 'reviewed_by')
            .order_by('-created_at')
        )

    @extend_schema(
        summary="Approve role application",
        description="Approve a pending role application. Adds the requested CompanyType to the company.",
        responses={200: CompanyRoleApplicationSerializer, 400: OpenApiResponse(description="Already processed")},
        tags=['Accounts'],
    )
    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """POST /api/v1/accounts/role-applications/{id}/approve/"""
        app = self.get_object()
        result, error = services.approve_role_application(app, request.user)
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(result).data)

    @extend_schema(
        summary="Reject role application",
        description="Reject a pending role application with an optional reason.",
        request=inline_serializer('RejectRequest', fields={
            'reason': drf_serializers.CharField(required=False, default=''),
        }),
        responses={200: CompanyRoleApplicationSerializer, 400: OpenApiResponse(description="Already processed")},
        tags=['Accounts'],
    )
    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """POST /api/v1/accounts/role-applications/{id}/reject/"""
        app = self.get_object()
        reason = request.data.get('reason', '')
        result, error = services.reject_role_application(app, request.user, reason)
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(result).data)
