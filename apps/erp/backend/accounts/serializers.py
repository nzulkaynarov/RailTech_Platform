import json

from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from .models import (
    Company,
    CompanyDocumentProfile,
    CompanyMember,
    CompanyRole,
    CompanySettings,
    CompanyType,
    CustomUser,
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
    # Что РЕАЛЬНО напечатается при включённом наследовании. Форма настроек показывала сырую
    # строку профиля — пустые «Юр. адрес» и «Банковские реквизиты», хотя документ рядом печатал
    # и адрес, и р/с с МФО из карточки компании. Продавец делал вывод, что реквизитов у его
    # документов нет (найдено прогоном глазами 19-08). Считает ТА ЖЕ функция, что и печать.
    inherited_preview = serializers.SerializerMethodField()

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
            "inherited_preview",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "company", "logo", "created_at", "updated_at", "inherited_preview"]

    def get_logo_url(self, obj) -> str | None:
        if not obj.logo:
            return None
        request = self.context.get("request")
        url = obj.logo.url
        return request.build_absolute_uri(url) if request else url

    @extend_schema_field(serializers.DictField(child=serializers.CharField(), allow_null=True))
    def get_inherited_preview(self, obj) -> dict | None:
        """Значения, которые НАПЕЧАТАЮТСЯ при включённом наследовании из карточки компании.

        Считает та же функция, что и печать (`crm.services.documents.brand`), поэтому форма
        настроек и готовый документ не могут разойтись. Нужно ровно затем, что заблокированные
        поля показывали пустоту, а документ рядом печатал адрес и банковские реквизиты.
        """
        from copy import copy

        from crm.services.documents.brand import _apply_company_defaults

        company = getattr(obj, "company", None)
        if company is None:
            return None
        row = copy(obj)
        _apply_company_defaults(company, row)
        return {
            "legal_name": row.legal_name or "",
            "inn": row.inn or "",
            "legal_address": row.legal_address or "",
            "bank_details": row.bank_details or "",
        }


class CompanyRoleSerializer(serializers.ModelSerializer):
    """A company-defined role with its permission set (the access matrix)."""

    member_count = serializers.SerializerMethodField()

    class Meta:
        model = CompanyRole
        fields = ["id", "company", "name", "permissions", "is_system", "member_count", "created_at", "updated_at"]
        read_only_fields = ["company", "is_system", "created_at", "updated_at"]

    def get_member_count(self, obj) -> int | None:
        return getattr(obj, "member_count", None) if hasattr(obj, "member_count") else obj.members.count()


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
    user_count = serializers.SerializerMethodField()
    company_types = serializers.SerializerMethodField()
    # Тип компании ЗАПИСЫВАЕТСЯ — по коду, а не по идентификатору справочника (Rule 2).
    #
    # До 26-08 типы были только на чтение, и операторская форма реестра не имела поля типа
    # вовсе: заведённый оператором арендатор не попадал ни в одну вкладку ТОГО ЖЕ экрана,
    # который фильтрует именно по типу. Задать тип можно было единственным способом — через
    # инженерный мастер Unfold. Экран обязан владеть полем, по которому сам фильтрует.
    types = serializers.SlugRelatedField(
        slug_field="code",
        many=True,
        required=False,
        queryset=CompanyType.objects.filter(is_active=True),
        write_only=True,
    )
    # Способность удалить объявляется ЗАРАНЕЕ (Salesforce `deletable`): кнопка, которая
    # гарантированно упрётся в отказ, — тупик. `delete_blocker` несёт причину с держателями.
    delete_blocker = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "inn",
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
            "user_count",
            "company_types",
            "types",
            "is_active",
            "archived_at",
            "archived_reason",
            "can_delete",
            "delete_blocker",
        ]
        # Trust signals are platform verdicts: a company must not self-set them.
        # `is_active` только на чтение: архив — действие со следом (`archive`/`unarchive`),
        # а не поле формы.
        read_only_fields = [
            "trust_score",
            "created_at",
            "is_active",
            "archived_at",
            "archived_reason",
        ]

    def get_user_count(self, obj) -> int:
        # Use len() to leverage prefetched members cache instead of extra COUNT query
        try:
            return len(obj.members.all())
        except AttributeError:
            return 0

    def get_delete_blocker(self, obj) -> str | None:
        """Причина, по которой компанию нельзя удалить, — или None.

        Считается только для операторского контекста: у члена компании такой кнопки нет, а
        обход держателей стоит нескольких запросов на строку.
        """
        request = self.context.get("request")
        if not (request and getattr(request.user, "is_superuser", False)):
            return None
        from accounts.services.company_lifecycle import can_delete_company

        return can_delete_company(obj)

    def get_can_delete(self, obj) -> bool:
        return self.get_delete_blocker(obj) is None

    def get_company_types(self, obj) -> list:
        # Use Python list comprehension to leverage prefetched types cache
        return [t.code for t in obj.types.all()]


class PrimaryCompanyLightSerializer(serializers.ModelSerializer):
    """Lightweight company serializer for embedding into UserSerializer.primary_company.
    Avoids nested members/types — saves several SQL queries per request."""

    company_types = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "inn",
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
    # Переходный алиас для SPA до чистки фронтенда (M1-ERP-02 волна 1b): администратор = superuser.
    is_platform_admin = serializers.BooleanField(source="is_superuser", read_only=True)

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
            "is_platform_admin",
            "is_2fa_enabled",
            "is_active",
            "memberships",
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

    def get_workspace_role(self, obj) -> str | None:
        # Leverage prefetched memberships — no extra SQL
        for m in obj.memberships.all():
            if m.is_primary and m.is_active and m.role:
                return m.role.code
        return None


class PlatformUserCreateSerializer(serializers.Serializer):
    """Вход формы «Новый пользователь» в операторской панели.

    Отдельный сериализатор, а не `UserSerializer`: у того `role` лежит в `read_only_fields`
    (правильно для правки — роль меняется отдельным действием с проверкой инвариантов), а
    `username` обязателен на уровне модели. Форма же спрашивает email и роль — и обе должны
    действовать. Роль принимаем КОДОМ (Rule 2), как и весь остальной фронт.
    """

    email = serializers.EmailField()
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=32)
    position = serializers.CharField(required=False, allow_blank=True, max_length=120)
    role = serializers.CharField(required=False, allow_blank=True, max_length=32)


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
    # Переходный алиас для SPA до чистки фронтенда (M1-ERP-02 волна 1b): администратор = superuser.
    is_platform_admin = serializers.BooleanField(source="is_superuser", read_only=True)
    # Per-membership flags for the primary company. Frontend uses these to
    # filter the BUYER/SELLER/MANUFACTURER context-switcher.
    can_sell = serializers.SerializerMethodField()
    can_buy = serializers.SerializerMethodField()
    # ПЕРЕХОДНОЕ поле (M1-ERP-02 волна 2): подписок больше нет, SPA ещё читает флаг до чистки
    # фронтенда. True для пользователя со стороны продавца, None — иначе. Убрать вместе с SPA.
    seller_subscription_operational = serializers.SerializerMethodField()
    is_superuser = serializers.BooleanField(read_only=True)
    # ADR-0005 (unified nav, Phase B): ONE explicit capability object the frontend's
    # buildNavigation() reads to render/gate the single nav from — instead of re-deriving it
    # from scattered company_types/can_sell/can_buy fields. UI gating
    # only; backend enforcement stays independent (member_has_permission).
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
            "is_platform_admin",
            "is_superuser",
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

    def get_seller_subscription_operational(self, obj) -> bool | None:
        from accounts.services import primary_seller_company_id

        return True if primary_seller_company_id(obj) is not None else None

    def get_capabilities(self, obj):
        """Consolidated effective-capability object (ADR-0005). `permissions` are the member's
        effective CompanyRole permission codes — is_system role → ALL_PERMISSIONS (mirrors
        CompanyRole.has_perm's short-circuit, so a perm added later isn't wrongly missing for an
        existing company admin). Drives the unified nav's per-item `requires` gates."""
        from accounts.services import is_seller, primary_seller_company_id
        from sourcing.ai_spend_cap import ai_daily_usage

        from .constants import ALL_PERMISSIONS

        membership = self._primary_membership(obj)
        permissions = []
        if membership and getattr(membership, "company_role", None):
            role = membership.company_role
            permissions = list(ALL_PERMISSIONS) if role.is_system else list(role.permissions or [])
        seller_company_id = primary_seller_company_id(obj)
        has_seller_context = seller_company_id is not None
        ai_usage = ai_daily_usage(obj)
        # `can_sell` здесь — «пользователь на стороне ПРОДАВЦА», ровно как это понимает авторизация
        # (`is_seller`: активное членство с can_sell И компания типа SUPPLIER/MANUFACTURER).
        # Плоское поле `can_sell` выше по сериализатору — флаг УЧАСТНИКА и типа компании не знает;
        # он по умолчанию True у любого члена, поэтому SPA показывала продавцовские поверхности
        # члену чисто покупательской компании (аудит UI 2026-07-30). Две правды свелись в одну.
        return {
            "can_buy": self.get_can_buy(obj),
            "can_sell": is_seller(obj),
            # ПЕРЕХОДНЫЕ ключи (M1-ERP-02 волна 2): подписки, DEMO и платный гейт отправки КП
            # удалены — отправку решает право роли `quote.send` (send_to_client). SPA до чистки
            # фронтенда ещё гейтит навигацию и конструктор КП по этим двум флагам; для стороны
            # продавца они всегда истинны. Убрать вместе с SPA.
            "subscription_active": has_seller_context,
            "can_send_quotes": has_seller_context,
            # Wave B: a "solo seller" is a seller company with exactly ONE active member who can
            # sell — for them the deal-claim button is pure noise (nobody else to claim against),
            # so the SPA hides it. UI-only signal; claim/routing services stay authoritative.
            "is_solo_seller": self._is_solo_seller(seller_company_id),
            # R4 §7.4: ОСТАТОК дневного лимита ИИ — информация, а не гейт. Механизм потолка уже
            # есть (sourcing/ai_spend_cap.py), не хватало видимости: пользователь узнавал о лимите,
            # только упёршись в 429 посреди работы. Ни одна кнопка от этих полей не выключается —
            # запрещает по-прежнему ТОЛЬКО enqueue_ai_job. cap/remaining = null — БЕЗЛИМИТ
            # (отключённый потолок, администратор), это отличимо от «осталось 0».
            "ai_daily_used": ai_usage["used"],
            "ai_daily_cap": ai_usage["cap"],
            "ai_daily_remaining": ai_usage["remaining"],
            "permissions": permissions,
            "is_platform_admin": bool(getattr(obj, "is_superuser", False)),
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


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)


# ──────────────────────────────────────────────────────────────────────────
# Admin-facing serializers (Phase 3 deferred)
# ──────────────────────────────────────────────────────────────────────────


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
