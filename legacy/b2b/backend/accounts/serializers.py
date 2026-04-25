from rest_framework import serializers

from .models import (
    Company, CompanyMember, CompanyRoleApplication, CustomUser,
    KYCDocument, SupplierSubscription,
)


class KYCDocumentSerializer(serializers.ModelSerializer):
    doc_type_display = serializers.CharField(source='doc_type.name', read_only=True)

    class Meta:
        model = KYCDocument
        fields = ['id', 'doc_type', 'doc_type_display', 'file', 'original_filename', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_at', 'original_filename', 'doc_type_display']


class CompanyMemberSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    role_code = serializers.CharField(source='role.code', read_only=True)
    company_name = serializers.CharField(source='company.name', read_only=True)

    class Meta:
        model = CompanyMember
        fields = [
            'id', 'user', 'user_email', 'company', 'company_name',
            'role', 'role_code', 'role_name', 'is_primary', 'is_active',
            'can_sell', 'can_buy', 'joined_at',
        ]


class CompanySerializer(serializers.ModelSerializer):
    kyc_documents = KYCDocumentSerializer(many=True, read_only=True)
    user_count = serializers.SerializerMethodField()
    verification_status_name = serializers.CharField(source='verification_status.name', read_only=True)
    verification_status_code = serializers.CharField(source='verification_status.code', read_only=True)
    company_types = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            'id', 'name', 'inn', 'verification_status', 'verification_status_name',
            'verification_status_code', 'is_verified', 'has_iso9001', 'trust_score',
            'bank_account', 'mfo', 'legal_address', 'phone',
            'contact_person', 'country', 'website', 'email', 'logo', 'kyc_notes',
            'created_at', 'kyc_documents', 'user_count', 'company_types'
        ]
        read_only_fields = ['verification_status', 'created_at']

    def get_user_count(self, obj):
        # Use len() to leverage prefetched members cache instead of extra COUNT query
        try:
            return len(obj.members.all())
        except AttributeError:
            return 0

    def get_company_types(self, obj):
        # Use Python list comprehension to leverage prefetched types cache
        return [t.code for t in obj.types.all()]


class PrimaryCompanyLightSerializer(serializers.ModelSerializer):
    """Lightweight company serializer for embedding into UserSerializer.primary_company.
    Avoids nested kyc_documents/members/types — saves 4-5 SQL queries per request."""
    verification_status_name = serializers.CharField(source='verification_status.name', read_only=True, default=None)
    verification_status_code = serializers.CharField(source='verification_status.code', read_only=True, default=None)
    company_types = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            'id', 'name', 'inn', 'verification_status', 'verification_status_name',
            'verification_status_code', 'is_verified', 'country', 'logo',
            'company_types',
        ]

    def get_company_types(self, obj):
        return [t.code for t in obj.types.all()]


class UserSerializer(serializers.ModelSerializer):
    memberships = CompanyMemberSerializer(many=True, read_only=True)
    primary_company = PrimaryCompanyLightSerializer(read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    role_code = serializers.CharField(source='role.code', read_only=True)
    role_data = serializers.SerializerMethodField()
    workspace_role = serializers.SerializerMethodField()
    kyc_status = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone', 'avatar', 'role', 'role_code', 'role_name',
            'role_data', 'workspace_role', 'kyc_status',
            'is_active', 'memberships', 'primary_company',
            'last_login', 'date_joined',
        ]
        read_only_fields = ['id', 'role', 'last_login', 'date_joined']

    def get_role_data(self, obj):
        if obj.role:
            return {
                'code': obj.role.code,
                'name': obj.role.name,
            }
        return None

    def get_workspace_role(self, obj):
        # Leverage prefetched memberships — no extra SQL
        for m in obj.memberships.all():
            if m.is_primary and m.is_active and m.role:
                return m.role.code
        return None

    def get_kyc_status(self, obj):
        if obj.primary_company and obj.primary_company.verification_status:
            return obj.primary_company.verification_status.code
        return None


class MeSerializer(serializers.ModelSerializer):
    """Lightweight serializer for /accounts/me/ — minimal queries.
    Skips nested memberships (frontend uses workspace_role + capabilities instead)."""
    primary_company = PrimaryCompanyLightSerializer(read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)
    role_code = serializers.CharField(source='role.code', read_only=True)
    role_data = serializers.SerializerMethodField()
    workspace_role = serializers.SerializerMethodField()
    kyc_status = serializers.SerializerMethodField()
    is_platform_admin = serializers.BooleanField(read_only=True)
    # Per-membership flags for the primary company. Frontend uses these to
    # filter the BUYER/SELLER/MANUFACTURER context-switcher.
    can_sell = serializers.SerializerMethodField()
    can_buy = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'phone', 'avatar', 'role', 'role_code', 'role_name',
            'role_data', 'workspace_role', 'kyc_status',
            'is_platform_admin',
            'can_sell', 'can_buy',
            'is_active', 'primary_company',
            'last_login', 'date_joined',
        ]
        read_only_fields = ['id', 'role', 'last_login', 'date_joined']

    def get_role_data(self, obj):
        if obj.role:
            return {
                'code': obj.role.code,
                'name': obj.role.name,
            }
        return None

    def _primary_membership(self, obj):
        for m in obj.memberships.all():
            if m.is_primary and m.is_active:
                return m
        return None

    def get_workspace_role(self, obj):
        membership = self._primary_membership(obj)
        return membership.role.code if (membership and membership.role) else None

    def get_can_sell(self, obj):
        membership = self._primary_membership(obj)
        return bool(membership and membership.can_sell)

    def get_can_buy(self, obj):
        membership = self._primary_membership(obj)
        # If no primary membership (e.g. platform super-admin before seed),
        # default to True so UI isn't accidentally locked down.
        return bool(membership.can_buy) if membership else True

    def get_kyc_status(self, obj):
        if obj.primary_company and obj.primary_company.verification_status:
            return obj.primary_company.verification_status.code
        return None


class KYCVerificationSerializer(serializers.Serializer):
    status_code = serializers.CharField(help_text="Code from VerificationStatus (e.g. 'L2_VERIFIED')")
    comment = serializers.CharField(required=False, allow_blank=True)


class RegisterInterestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)


class SetupPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(min_length=8)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    password = serializers.CharField(min_length=8)


class SubmitProfileSerializer(serializers.Serializer):
    inn = serializers.CharField(max_length=20)
    companyName = serializers.CharField(max_length=255)
    role_code = serializers.CharField(max_length=50, help_text="WorkspaceRole code (e.g. 'OWNER')")
    company_type = serializers.CharField(max_length=50, required=False, default='CLIENT',
                                         help_text="CompanyType code (e.g. 'CLIENT', 'MANUFACTURER', 'SUPPLIER')")


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)


# ──────────────────────────────────────────────────────────────────────────
# Admin-facing serializers (Phase 3 deferred)
# ──────────────────────────────────────────────────────────────────────────


class SupplierSubscriptionSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    company_inn = serializers.CharField(source='company.inn', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True, default=None)
    plan_display = serializers.CharField(source='get_plan_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = SupplierSubscription
        fields = [
            'id', 'company', 'company_name', 'company_inn',
            'plan', 'plan_display', 'status', 'status_display',
            'monthly_rate', 'currency', 'currency_code',
            'valid_from', 'valid_until',
            'last_payment_date', 'next_payment_date',
            'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'company_name', 'company_inn', 'created_at', 'updated_at']


class CompanyRoleApplicationSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    company_inn = serializers.CharField(source='company.inn', read_only=True)
    requested_type_name = serializers.CharField(source='requested_type.name', read_only=True)
    requested_type_code = serializers.CharField(source='requested_type.code', read_only=True)
    submitted_by_email = serializers.CharField(source='submitted_by.email', read_only=True, default=None)
    reviewed_by_email = serializers.CharField(source='reviewed_by.email', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = CompanyRoleApplication
        fields = [
            'id', 'company', 'company_name', 'company_inn',
            'requested_type', 'requested_type_name', 'requested_type_code',
            'status', 'status_display',
            'submitted_by', 'submitted_by_email',
            'contract_file', 'nda_file', 'partnership_agreement',
            'reviewed_by', 'reviewed_by_email', 'review_notes', 'reviewed_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'company_name', 'company_inn',
            'requested_type_name', 'requested_type_code',
            'submitted_by_email', 'reviewed_by_email',
            'status_display', 'created_at', 'updated_at',
        ]
