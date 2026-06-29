from django.conf import settings
from django.core.validators import RegexValidator
from rest_framework import serializers

from .models import (
    Company,
    CompanyDocumentProfile,
    CompanyMember,
    CompanyRole,
    CompanyRoleApplication,
    CompanySettings,
    CustomUser,
    KYCDocument,
    OperatorRole,
    SupplierSubscription,
)


class CompanySettingsSerializer(serializers.ModelSerializer):
    """A selling company's КП defaults + document-numbering prefix.

    Read/update by the company OWNER for THEIR OWN company. FK defaults
    (delivery_basis / cost_currency) are exposed AND written as master-data CODES
    (e.g. "USD", "FCA") — the service resolves them — so the field names below are
    read-only projections; PATCH bodies carry `default_cost_currency` /
    `default_delivery_basis` codes which the view hands to update_company_settings.
    """

    default_cost_currency_code = serializers.CharField(
        source="default_cost_currency.code", read_only=True, allow_null=True
    )
    default_delivery_basis_code = serializers.CharField(
        source="default_delivery_basis.code", read_only=True, allow_null=True
    )

    class Meta:
        model = CompanySettings
        fields = [
            "id",
            "company",
            "default_cost_currency_code",
            "default_delivery_basis_code",
            "default_vat_rate",
            "default_margin_percent",
            "default_offer_validity_days",
            "min_margin_percent",
            "target_margin_percent",
            "doc_number_prefix",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "company", "created_at", "updated_at"]


class CompanyDocumentProfileSerializer(serializers.ModelSerializer):
    """The branded requisites a company prints on its own КП / contract documents.

    Read/update by the company OWNER for THEIR OWN company. `logo` is read-only here
    (multipart upload goes through the dedicated upload-document-logo action, mirroring
    the company-logo pattern); all textual requisites are flat-writable.
    """

    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = CompanyDocumentProfile
        fields = [
            "id",
            "company",
            "logo",
            "logo_url",
            "legal_name",
            "inn",
            "legal_address",
            "bank_details",
            "signatory_name",
            "signatory_position",
            "footer_text",
            "accent_color",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "company", "logo", "created_at", "updated_at"]

    def get_logo_url(self, obj):
        if not obj.logo:
            return None
        request = self.context.get("request")
        url = obj.logo.url
        return request.build_absolute_uri(url) if request else url


class CompanyRoleSerializer(serializers.ModelSerializer):
    """A company-defined role with its permission set (the access matrix)."""

    member_count = serializers.SerializerMethodField()

    class Meta:
        model = CompanyRole
        fields = ["id", "company", "name", "permissions", "is_system", "member_count", "created_at", "updated_at"]
        read_only_fields = ["company", "is_system", "created_at", "updated_at"]

    def get_member_count(self, obj):
        return getattr(obj, "member_count", None) if hasattr(obj, "member_count") else obj.members.count()


class OperatorRoleSerializer(serializers.ModelSerializer):
    """A platform-operator sub-role with its capability set (ADR-0004 G1)."""

    operator_count = serializers.SerializerMethodField()

    class Meta:
        model = OperatorRole
        fields = [
            "id", "code", "name", "permissions", "is_system",
            "description", "operator_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "code", "is_system", "created_at", "updated_at"]

    def get_operator_count(self, obj):
        return getattr(obj, "operator_count", None) if hasattr(obj, "operator_count") else obj.operators.count()


class KYCDocumentSerializer(serializers.ModelSerializer):
    doc_type_display = serializers.CharField(source="doc_type.name", read_only=True)

    class Meta:
        model = KYCDocument
        fields = ["id", "doc_type", "doc_type_display", "file", "original_filename", "uploaded_at"]
        read_only_fields = ["id", "uploaded_at", "original_filename", "doc_type_display"]


class CompanyMemberSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    role_code = serializers.CharField(source="role.code", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    company_role_name = serializers.CharField(source="company_role.name", read_only=True)

    class Meta:
        model = CompanyMember
        fields = [
            "id",
            "user",
            "user_email",
            "company",
            "company_name",
            "role",
            "role_code",
            "role_name",
            "company_role",
            "company_role_name",
            "is_primary",
            "is_active",
            "can_sell",
            "can_buy",
            "joined_at",
        ]


class CompanySerializer(serializers.ModelSerializer):
    kyc_documents = KYCDocumentSerializer(many=True, read_only=True)
    user_count = serializers.SerializerMethodField()
    verification_status_name = serializers.CharField(source="verification_status.name", read_only=True)
    verification_status_code = serializers.CharField(source="verification_status.code", read_only=True)
    company_types = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "inn",
            "verification_status",
            "verification_status_name",
            "verification_status_code",
            "is_verified",
            "has_iso9001",
            "trust_score",
            "bank_account",
            "mfo",
            "legal_address",
            "phone",
            "contact_person",
            "country",
            "website",
            "email",
            "logo",
            "created_at",
            "kyc_documents",
            "user_count",
            "company_types",
        ]
        # kyc_notes is intentionally NOT exposed — it holds internal KYC-manager
        # notes ("не видны клиенту"). verify-kyc writes it directly on the model.
        # Trust signals are platform verdicts: a company must not self-set them.
        read_only_fields = ["verification_status", "is_verified", "trust_score", "created_at"]

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

    verification_status_name = serializers.CharField(source="verification_status.name", read_only=True, default=None)
    verification_status_code = serializers.CharField(source="verification_status.code", read_only=True, default=None)
    company_types = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "inn",
            "verification_status",
            "verification_status_name",
            "verification_status_code",
            "is_verified",
            "country",
            "logo",
            "company_types",
        ]

    def get_company_types(self, obj):
        return [t.code for t in obj.types.all()]


class UserSerializer(serializers.ModelSerializer):
    memberships = CompanyMemberSerializer(many=True, read_only=True)
    primary_company = PrimaryCompanyLightSerializer(read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    role_code = serializers.CharField(source="role.code", read_only=True)
    role_data = serializers.SerializerMethodField()
    workspace_role = serializers.SerializerMethodField()
    kyc_status = serializers.SerializerMethodField()
    operator_role_data = serializers.SerializerMethodField()
    is_platform_admin = serializers.BooleanField(read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "position",
            "avatar",
            "role",
            "role_code",
            "role_name",
            "role_data",
            "workspace_role",
            "kyc_status",
            "operator_role",
            "operator_role_data",
            "is_platform_admin",
            "is_active",
            "memberships",
            "primary_company",
            "last_login",
            "date_joined",
        ]
        read_only_fields = ["id", "role", "operator_role", "last_login", "date_joined"]

    def get_operator_role_data(self, obj):
        op = obj.operator_role
        if op:
            return {"id": op.id, "code": op.code, "name": op.name}
        return None

    def get_role_data(self, obj):
        if obj.role:
            return {
                "code": obj.role.code,
                "name": obj.role.name,
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


class SelfUpdateSerializer(serializers.ModelSerializer):
    """Fields a user may edit on their OWN profile via /users/update-me/.

    Deliberately narrow: email/username are the login identity (changing them
    needs a separate verified flow), and is_active/role are platform-controlled.
    The shared UserSerializer keeps those writable for admin user management —
    self-service must not.
    """

    class Meta:
        model = CustomUser
        fields = ["first_name", "last_name", "phone", "position", "avatar"]


class MeSerializer(serializers.ModelSerializer):
    """Lightweight serializer for /accounts/me/ — minimal queries.
    Skips nested memberships (frontend uses workspace_role + capabilities instead)."""

    primary_company = PrimaryCompanyLightSerializer(read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    role_code = serializers.CharField(source="role.code", read_only=True)
    role_data = serializers.SerializerMethodField()
    workspace_role = serializers.SerializerMethodField()
    kyc_status = serializers.SerializerMethodField()
    is_platform_admin = serializers.BooleanField(read_only=True)
    # Per-membership flags for the primary company. Frontend uses these to
    # filter the BUYER/SELLER/MANUFACTURER context-switcher.
    can_sell = serializers.SerializerMethodField()
    can_buy = serializers.SerializerMethodField()
    # Whether the seller company has an operational subscription. Lets the UI show
    # a "subscription required" banner before the seller hits SUBSCRIPTION_REQUIRED
    # on a write. None for non-sellers (banner only renders for can_sell users).
    seller_subscription_operational = serializers.SerializerMethodField()
    # The platform operator's own sub-role + effective permission codes, so the React admin
    # can GATE controls client-side (audit F3-UX). Without this the UI showed Add/Edit/Delete
    # to a view-only operator, which only 403'd on save.
    operator_role_code = serializers.CharField(source="operator_role.code", read_only=True)
    operator_permissions = serializers.SerializerMethodField()
    is_superuser = serializers.BooleanField(read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "position",
            "avatar",
            "role",
            "role_code",
            "role_name",
            "role_data",
            "workspace_role",
            "kyc_status",
            "is_platform_admin",
            "is_superuser",
            "operator_role_code",
            "operator_permissions",
            "can_sell",
            "can_buy",
            "seller_subscription_operational",
            "is_active",
            "primary_company",
            "last_login",
            "date_joined",
        ]
        read_only_fields = ["id", "role", "last_login", "date_joined"]

    def get_role_data(self, obj):
        if obj.role:
            return {
                "code": obj.role.code,
                "name": obj.role.name,
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

    def get_seller_subscription_operational(self, obj):
        from accounts.services import company_has_operational_subscription, primary_seller_company_id

        company_id = primary_seller_company_id(obj)
        if company_id is None:
            return None
        return company_has_operational_subscription(company_id)

    def get_operator_permissions(self, obj):
        """Effective operator permission codes for client-side capability gating.

        None = UNRESTRICTED — superuser, an operator with no sub-role (backward-compat full
        access), or an `is_system` sub-role (e.g. SUPER_OPERATOR). The is_system case MUST
        mirror OperatorRole.has_perm's short-circuit (`return self.is_system or code in ...`),
        otherwise a NEW permission code added later as a nav `requires` would be wrongly hidden
        from existing super-operators whose stored permission JSON predates it (FE/BE authz
        desync — audit M7). A list = exactly the codes the assigned sub-role grants, so the
        React admin hides controls the operator can't use.
        """
        if not getattr(obj, "is_platform_admin", False):
            return None
        op_role = obj.operator_role
        if getattr(obj, "is_superuser", False) or op_role is None or op_role.is_system:
            return None
        return list(op_role.permissions or [])


class KYCVerificationSerializer(serializers.Serializer):
    status_code = serializers.CharField(help_text="Code from VerificationStatus (e.g. 'L2_VERIFIED')")
    comment = serializers.CharField(required=False, allow_blank=True)


class RegisterInterestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(
        max_length=20,
        validators=[RegexValidator(settings.UZ_PHONE_REGEX, "PHONE_INVALID")],
        help_text="Uzbekistan format: +998XXXXXXXXX",
    )


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
    # Minimal onboarding (Phase 1): everyone self-registers as a Buyer (CLIENT)
    # and becomes OWNER of their own company. INN and company type are deferred —
    # INN is collected later at KYC, selling is granted via CompanyRoleApplication.
    companyName = serializers.CharField(max_length=255)
    position = serializers.CharField(max_length=120, help_text="Free-text job title, e.g. 'Директор по закупкам'")


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)


# ──────────────────────────────────────────────────────────────────────────
# Admin-facing serializers (Phase 3 deferred)
# ──────────────────────────────────────────────────────────────────────────


class SupplierSubscriptionSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)
    company_inn = serializers.CharField(source="company.inn", read_only=True)
    currency_code = serializers.CharField(source="currency.code", read_only=True, default=None)
    plan_display = serializers.CharField(source="get_plan_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SupplierSubscription
        fields = [
            "id",
            "company",
            "company_name",
            "company_inn",
            "plan",
            "plan_display",
            "status",
            "status_display",
            "monthly_rate",
            "currency",
            "currency_code",
            "valid_from",
            "valid_until",
            "last_payment_date",
            "next_payment_date",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "company_name", "company_inn", "created_at", "updated_at"]


class CompanyRoleApplicationSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)
    company_inn = serializers.CharField(source="company.inn", read_only=True)
    requested_type_name = serializers.CharField(source="requested_type.name", read_only=True)
    requested_type_code = serializers.CharField(source="requested_type.code", read_only=True)
    submitted_by_email = serializers.CharField(source="submitted_by.email", read_only=True, default=None)
    reviewed_by_email = serializers.CharField(source="reviewed_by.email", read_only=True, default=None)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = CompanyRoleApplication
        fields = [
            "id",
            "company",
            "company_name",
            "company_inn",
            "requested_type",
            "requested_type_name",
            "requested_type_code",
            "status",
            "status_display",
            "submitted_by",
            "submitted_by_email",
            "contract_file",
            "nda_file",
            "partnership_agreement",
            "reviewed_by",
            "reviewed_by_email",
            "review_notes",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            # Moderation + ownership fields — set by the server on create / by the admin's
            # approve-reject action, NEVER writable by the applicant (audit M2: an OWNER could
            # otherwise forge {status:APPROVED, reviewed_by:<admin>} or move `company` to another
            # tenant via PATCH while the app was PENDING).
            "company",
            "status",
            "submitted_by",
            "reviewed_by",
            "review_notes",
            "reviewed_at",
            "company_name",
            "company_inn",
            "requested_type_name",
            "requested_type_code",
            "submitted_by_email",
            "reviewed_by_email",
            "status_display",
            "created_at",
            "updated_at",
        ]
