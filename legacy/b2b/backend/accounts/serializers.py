import json

from django.conf import settings
from django.core.validators import RegexValidator
from rest_framework import serializers
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from .models import (
    Company,
    CompanyDocumentProfile,
    CompanyEntitlement,
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
            "payment_terms_days",
            "default_payment_terms",
            "default_warranty_months",
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
            "secondary_color",
            "layout_preset",
            "font_family",
            "cover_letter_text",
            "show_cover_letter",
            # Формулировки документов (spec-documents-editable-and-uniform): проза договора и
            # акта редактируется компанией, каркас остаётся кодом.
            "contract_acceptance_text",
            "contract_liability_text",
            "contract_extra_terms_text",
            "act_closing_text",
            "show_bank_in_header",
            "use_company_defaults",
            "show_logo",
            "show_lead_time",
            "show_fx_note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "company", "logo", "created_at", "updated_at"]

    def get_logo_url(self, obj) -> str | None:
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

    def get_member_count(self, obj) -> int | None:
        return getattr(obj, "member_count", None) if hasattr(obj, "member_count") else obj.members.count()


class OperatorRoleSerializer(serializers.ModelSerializer):
    """A platform-operator sub-role with its capability set (ADR-0004 G1)."""

    operator_count = serializers.SerializerMethodField()

    class Meta:
        model = OperatorRole
        fields = [
            "id",
            "code",
            "name",
            "permissions",
            "is_system",
            "description",
            "operator_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "code", "is_system", "created_at", "updated_at"]

    def get_operator_count(self, obj) -> int | None:
        return getattr(obj, "operator_count", None) if hasattr(obj, "operator_count") else obj.operators.count()


class KYCDocumentSerializer(serializers.ModelSerializer):
    # `doc_type_display` is the Russian-only lookup NAME — presentation fallback only.
    # `doc_type_code` is the stable lookup CODE the SPA maps to a localized label (IRON RULE 2).
    doc_type_display = serializers.CharField(source="doc_type.name", read_only=True)
    doc_type_code = serializers.CharField(source="doc_type.code", read_only=True)

    class Meta:
        model = KYCDocument
        fields = ["id", "doc_type", "doc_type_code", "doc_type_display", "file", "original_filename", "uploaded_at"]
        read_only_fields = ["id", "uploaded_at", "original_filename", "doc_type_code", "doc_type_display"]


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

    def get_user_count(self, obj) -> int:
        # Use len() to leverage prefetched members cache instead of extra COUNT query
        try:
            return len(obj.members.all())
        except AttributeError:
            return 0

    def get_company_types(self, obj) -> list:
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

    def get_company_types(self, obj) -> list:
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
            "preferences",
            "role",
            "role_code",
            "role_name",
            "role_data",
            "workspace_role",
            "kyc_status",
            "operator_role",
            "operator_role_data",
            "is_platform_admin",
            "is_2fa_enabled",
            "is_active",
            "memberships",
            "primary_company",
            "last_login",
            "date_joined",
        ]
        read_only_fields = ["id", "role", "operator_role", "is_2fa_enabled", "last_login", "date_joined"]

    def get_operator_role_data(self, obj) -> dict | None:
        op = obj.operator_role
        if op:
            return {"id": op.id, "code": op.code, "name": op.name}
        return None

    def get_role_data(self, obj) -> dict | None:
        if obj.role:
            return {
                "code": obj.role.code,
                "name": obj.role.name,
            }
        return None

    def get_workspace_role(self, obj) -> str | None:
        # Leverage prefetched memberships — no extra SQL
        for m in obj.memberships.all():
            if m.is_primary and m.is_active and m.role:
                return m.role.code
        return None

    def get_kyc_status(self, obj) -> str | None:
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

    # Allow-list for the free-form `preferences` JSONField: keys, allowed
    # values, and a size cap so an authenticated user cannot persist arbitrary
    # or oversized JSON on their own record (LOW #7). The frontend only ever
    # writes {language, theme}; `timezone` is reserved (see model help_text).
    PREFERENCES_ALLOWED_KEYS = frozenset({"language", "theme", "timezone"})
    PREFERENCES_THEME_VALUES = frozenset({"light", "dark", "system"})
    PREFERENCES_TIMEZONE_MAX_LEN = 64
    PREFERENCES_MAX_BYTES = 2048

    class Meta:
        model = CustomUser
        fields = ["first_name", "last_name", "phone", "position", "avatar", "preferences"]

    def validate_preferences(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("PREFERENCES_INVALID")
        if len(json.dumps(value).encode("utf-8")) > self.PREFERENCES_MAX_BYTES:
            raise serializers.ValidationError("PREFERENCES_TOO_LARGE")

        unknown = set(value) - self.PREFERENCES_ALLOWED_KEYS
        if unknown:
            raise serializers.ValidationError("PREFERENCES_UNKNOWN_KEY")

        language = value.get("language")
        if language is not None:
            allowed_languages = {code for code, _label in settings.LANGUAGES}
            if language not in allowed_languages:
                raise serializers.ValidationError("PREFERENCES_INVALID_LANGUAGE")

        theme = value.get("theme")
        if theme is not None and theme not in self.PREFERENCES_THEME_VALUES:
            raise serializers.ValidationError("PREFERENCES_INVALID_THEME")

        timezone_value = value.get("timezone")
        if timezone_value is not None and (
            not isinstance(timezone_value, str) or len(timezone_value) > self.PREFERENCES_TIMEZONE_MAX_LEN
        ):
            raise serializers.ValidationError("PREFERENCES_INVALID_TIMEZONE")

        return value


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
    # ADR-0005 (unified nav, Phase B): ONE explicit capability object the frontend's
    # buildNavigation() reads to render/gate the single nav from — instead of re-deriving it
    # from scattered company_types/can_sell/can_buy/kyc/subscription/operator fields. UI gating
    # only; backend enforcement stays independent (member_has_permission / subscription / KYC-floor).
    capabilities = serializers.SerializerMethodField()

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
            "preferences",
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
            "capabilities",
            "is_2fa_enabled",
            "is_active",
            "primary_company",
            "last_login",
            "date_joined",
        ]
        read_only_fields = ["id", "role", "is_2fa_enabled", "last_login", "date_joined"]

    def get_role_data(self, obj) -> dict | None:
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

    def get_workspace_role(self, obj) -> str | None:
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

    def get_kyc_status(self, obj) -> str | None:
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

    def get_capabilities(self, obj):
        """Consolidated effective-capability object (ADR-0005). `permissions` are the member's
        effective CompanyRole permission codes — is_system role → ALL_PERMISSIONS (mirrors
        CompanyRole.has_perm's short-circuit, so a perm added later isn't wrongly missing for an
        existing company admin). Drives the unified nav's per-item `requires` gates."""
        from accounts.services import is_demo, is_seller, primary_seller_company_id, quote_send_entitled
        from sourcing.ai_spend_cap import ai_daily_usage

        from .constants import ALL_PERMISSIONS, FeatureKey

        membership = self._primary_membership(obj)
        permissions = []
        if membership and getattr(membership, "company_role", None):
            role = membership.company_role
            permissions = list(ALL_PERMISSIONS) if role.is_system else list(role.permissions or [])
        # WP-H early-gate signals: surface the seller's quote.send eligibility to the КП builder so
        # blockers show BEFORE an hour of data entry, mirroring send_to_client's KYC→entitlement gate
        # order (SELLER_KYC_REQUIRED then QUOTE_SEND_NOT_ENTITLED). `can_send_quotes` folds all three
        # send preconditions (KYC L2+, quote.send entitlement, NOT demo); `quote_send_is_demo` lets the
        # UI show the distinct "output watermarked" message. UI-gating only — send_to_client stays
        # authoritative. None seller company → both False (no seller context to gate).
        seller_company_id = primary_seller_company_id(obj)
        ai_usage = ai_daily_usage(obj)
        # `can_sell` здесь — «пользователь на стороне ПРОДАВЦА», ровно как это понимает авторизация
        # (`is_seller`: активное членство с can_sell И компания типа SUPPLIER/MANUFACTURER).
        # Плоское поле `can_sell` выше по сериализатору — флаг УЧАСТНИКА и типа компании не знает;
        # он по умолчанию True у любого члена, поэтому SPA показывала продавцовские поверхности
        # члену чисто покупательской компании (аудит UI 2026-07-30). Две правды свелись в одну.
        return {
            "kyc_level": self.get_kyc_status(obj),
            "can_buy": self.get_can_buy(obj),
            "can_sell": is_seller(obj),
            "subscription_active": bool(self.get_seller_subscription_operational(obj)),
            "can_send_quotes": bool(seller_company_id and quote_send_entitled(seller_company_id)),
            "quote_send_is_demo": bool(seller_company_id and is_demo(seller_company_id, FeatureKey.QUOTE_SEND)),
            # Wave B: a "solo seller" is a seller company with exactly ONE active member who can
            # sell — for them the deal-claim button is pure noise (nobody else to claim against),
            # so the SPA hides it. UI-only signal; claim/routing services stay authoritative.
            "is_solo_seller": self._is_solo_seller(seller_company_id),
            # R4 §7.4: ОСТАТОК дневного лимита ИИ — информация, а не гейт. Механизм потолка уже
            # есть (sourcing/ai_spend_cap.py), не хватало видимости: пользователь узнавал о лимите,
            # только упёршись в 429 посреди работы. Ни одна кнопка от этих полей не выключается —
            # запрещает по-прежнему ТОЛЬКО enqueue_ai_job. cap/remaining = null — БЕЗЛИМИТ
            # (тариф Безлимит, отключённый потолок, оператор), это отличимо от «осталось 0».
            "ai_daily_used": ai_usage["used"],
            "ai_daily_cap": ai_usage["cap"],
            "ai_daily_remaining": ai_usage["remaining"],
            "permissions": permissions,
            "is_platform_admin": bool(getattr(obj, "is_platform_admin", False)),
            "operator_permissions": self.get_operator_permissions(obj),
        }

    @staticmethod
    def _is_solo_seller(seller_company_id) -> bool:
        """True when the seller company has exactly one active member with sell capability —
        the case where deal-claim is meaningless noise (Wave B). False for no seller context or
        any multi-seller team (claim still routes work there)."""
        if not seller_company_id:
            return False
        from accounts.models import CompanyMember

        return CompanyMember.objects.filter(company_id=seller_company_id, is_active=True, can_sell=True).count() == 1


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
    # CRM Phase D — a CB-invite token: claim an existing offline company instead of a new one.
    invite = serializers.CharField(required=False, allow_blank=True, default="")


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


class CompanyEntitlementSerializer(serializers.ModelSerializer):
    """Platform-admin view/CRUD of a company's feature entitlements (ADR-0006 Move 4 monetization)."""

    company_name = serializers.CharField(source="company.name", read_only=True)
    company_inn = serializers.CharField(source="company.inn", read_only=True)
    access_display = serializers.CharField(source="get_access_display", read_only=True)
    is_granted = serializers.SerializerMethodField()

    def get_is_granted(self, obj) -> bool:
        return obj.is_currently_granted()

    class Meta:
        model = CompanyEntitlement
        fields = [
            "id",
            "company",
            "company_name",
            "company_inn",
            "feature_key",
            "access",
            "access_display",
            "limit",
            "credits",
            "expires_at",
            "note",
            "is_granted",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "company_name",
            "company_inn",
            "access_display",
            "is_granted",
            "created_at",
            "updated_at",
        ]


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


class ActiveSessionSerializer(serializers.ModelSerializer):
    """One live refresh token = one session. `is_current` matches the row against
    the jti of THIS browser's HttpOnly refresh cookie (passed via context)."""

    is_current = serializers.SerializerMethodField()

    class Meta:
        model = OutstandingToken
        fields = ["id", "created_at", "expires_at", "is_current"]

    def get_is_current(self, obj) -> bool:
        current_jti = self.context.get("current_jti")
        return bool(current_jti) and obj.jti == current_jti
