from rest_framework import viewsets, status, views, permissions, exceptions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.generics import RetrieveAPIView
from rest_framework.parsers import MultiPartParser, FormParser

from django.db.models import Prefetch

from core.permissions import IsAdminUser, IsManagerOrAdmin

from . import services
from .models import (
    Company, CompanyMember, CompanyRoleApplication, CustomUser,
    SupplierSubscription,
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


class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.prefetch_related('kyc_documents', 'members').order_by('-created_at')
    serializer_class = CompanySerializer
    permission_classes = [permissions.IsAuthenticated, IsManagerOrAdmin]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # Admin / Manager check via SystemRole
        is_staff = request.user.is_staff or (request.user.role and request.user.role.is_staff_level)

        if not is_staff:
            # Check if user is a member of this company
            membership = CompanyMember.objects.filter(user=request.user, company=instance).exists()
            if not membership:
                raise exceptions.PermissionDenied("You can only view your own company.")
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='verify-kyc')
    def verify_kyc(self, request, pk=None):
        company = self.get_object()
        serializer = KYCVerificationSerializer(data=request.data)
        if serializer.is_valid():
            code = serializer.validated_data['status_code']
            comment = serializer.validated_data.get('comment', '')

            result, error = services.verify_company_kyc(
                company, request.user, level_code=code, require_documents=False
            )
            if error:
                return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

            if comment:
                result.kyc_notes = comment
                result.save(update_fields=['kyc_notes'])

            return Response({'status': 'Status updated', 'new_status': result.verification_status.name})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
            return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

        doc_type_code = request.data.get('doc_type', 'OTHER')
        doc, error = services.upload_kyc_document(company, file_obj, doc_type_code)
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(KYCDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path='delete-document/(?P<doc_id>[0-9]+)', url_name='delete-document')
    def delete_document(self, request, pk=None, doc_id=None):
        company = self.get_object()
        success, error = services.delete_kyc_document(company, int(doc_id))
        if error:
            return Response({'detail': error}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def team(self, request, pk=None):
        company = self.get_object()
        # Security check
        is_member = CompanyMember.objects.filter(user=request.user, company=company).exists()
        is_staff = request.user.is_staff or (request.user.role and request.user.role.is_staff_level)

        if not (is_member or is_staff):
            raise exceptions.PermissionDenied("You can only view your own team.")

        users = CustomUser.objects.filter(memberships__company=company).distinct()
        return Response(UserSerializer(users, many=True).data)

    @action(detail=True, methods=['post'])
    def invite(self, request, pk=None):
        """Invite a new team member to the company."""
        company = self.get_object()

        # Only company owner can invite
        membership = CompanyMember.objects.filter(
            user=request.user, company=company, is_active=True
        ).select_related('role').first()

        if not membership or membership.role.code != 'OWNER':
            is_staff = request.user.is_superuser or request.user.is_manager_or_admin
            if not is_staff:
                return Response({'error': 'Only company owner can invite members'},
                              status=status.HTTP_403_FORBIDDEN)

        email = request.data.get('email')
        role_code = request.data.get('role', 'PROCUREMENT_MANAGER')

        from .services import invite_workspace_member
        user, error = invite_workspace_member(company, email, role_code)
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class UserViewSet(viewsets.ModelViewSet):
    queryset = CustomUser.objects.all().select_related(
        'role',
    ).prefetch_related(
        Prefetch(
            'memberships',
            queryset=CompanyMember.objects.select_related(
                'company__verification_status',
                'role',
            ).prefetch_related(
                'company__kyc_documents__doc_type',
                'company__types',
                'company__members',
            ),
        ),
    ).order_by('-date_joined')
    serializer_class = UserSerializer
    # Use custom IsAdminUser that checks SystemRole.code == 'ADMIN', not Django's is_staff
    from core.permissions import IsAdminUser as CustomIsAdminUser
    permission_classes = [permissions.IsAuthenticated, CustomIsAdminUser]

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
        return Response({'message': 'Пароль успешно изменён'})

    @action(detail=False, methods=['patch'], url_path='update-me',
            permission_classes=[permissions.IsAuthenticated])
    def update_me(self, request):
        serializer = self.get_serializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='me',
            permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

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


class SupplierSubscriptionViewSet(viewsets.ModelViewSet):
    """
    CRUD + status actions for supplier subscriptions.
    Admin/Manager only.
    """
    serializer_class = SupplierSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated, IsManagerOrAdmin]
    filterset_fields = ['plan', 'status', 'company']
    search_fields = ['company__name', 'company__inn']
    ordering = ['-created_at']

    def get_queryset(self):
        return (
            SupplierSubscription.objects
            .select_related('company', 'currency')
            .order_by('-created_at')
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

    @action(detail=True, methods=['post'], url_path='suspend')
    def suspend(self, request, pk=None):
        """POST /api/v1/accounts/subscriptions/{id}/suspend/"""
        sub = self.get_object()
        services.change_subscription_status(
            SupplierSubscription.objects.filter(pk=sub.pk), 'SUSPENDED'
        )
        sub.refresh_from_db()
        return Response(self.get_serializer(sub).data)


class CompanyRoleApplicationViewSet(viewsets.ModelViewSet):
    """
    CRUD + approve/reject for company role applications.
    Admin/Manager only.
    """
    serializer_class = CompanyRoleApplicationSerializer
    permission_classes = [permissions.IsAuthenticated, IsManagerOrAdmin]
    filterset_fields = ['status', 'requested_type', 'company']
    search_fields = ['company__name', 'company__inn']
    ordering = ['-created_at']

    def get_queryset(self):
        return (
            CompanyRoleApplication.objects
            .select_related('company', 'requested_type', 'submitted_by', 'reviewed_by')
            .order_by('-created_at')
        )

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """POST /api/v1/accounts/role-applications/{id}/approve/"""
        app = self.get_object()
        result, error = services.approve_role_application(app, request.user)
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(result).data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """POST /api/v1/accounts/role-applications/{id}/reject/"""
        app = self.get_object()
        reason = request.data.get('reason', '')
        result, error = services.reject_role_application(app, request.user, reason)
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(result).data)
