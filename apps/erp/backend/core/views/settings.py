from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import SystemSetting
from core.permissions import ADMIN_ONLY, RoleGatedViewMixin

# ──────────────────────────────────────────────────────────────────────────
# System Settings (singleton)
# ──────────────────────────────────────────────────────────────────────────


class SystemSettingSerializer(drf_serializers.ModelSerializer):
    # Курс USD→UZS — только чтение и только из единого источника `finance.services.fx` (FIX-41, F-12):
    # ручного второго курса нет. Нет свежего курса ЦБ — null, SPA тогда не пересчитывает суммы в USD.
    exchange_rate_usd_uzs = drf_serializers.SerializerMethodField(
        help_text="Курс USD→UZS из справочника курсов (ЦБ РУз), только чтение; null — свежего курса нет."
    )

    @extend_schema_field({"type": "string", "format": "decimal", "nullable": True})
    def get_exchange_rate_usd_uzs(self, obj):
        from finance.services.fx import rate_to_str, resolve_rate

        resolved = resolve_rate("USD")
        return rate_to_str(resolved.rate) if resolved else None

    class Meta:
        model = SystemSetting
        # standard_margin removed from the API surface (P9): the pricing engine reads
        # CompanySettings.default_margin_percent, so this platform field was inert. The DB
        # column + pgtrigger history stay (dropping a column is riskier than it's worth) —
        # it is simply no longer read or written through the settings API.
        fields = [
            "vat_rate",
            "exchange_rate_usd_uzs",
            "platform_name",
            "support_email",
            "logo_url",
            "domain",
            "maintenance_mode",
            "is_two_factor_required",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


class SystemSettingsView(RoleGatedViewMixin, APIView):
    """
    GET  /api/v1/system-settings/ — read current settings (any authenticated user)
    PATCH /api/v1/system-settings/ — update settings (administrator = superuser only)
    """

    required_permissions = {
        "PATCH": ADMIN_ONLY,
        "PUT": ADMIN_ONLY,
    }

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get system settings",
        description=(
            "Returns current platform settings: VAT rate, margin, exchange rate, etc. "
            "Any authenticated user can read."
        ),
        responses={200: SystemSettingSerializer},
        tags=["System"],
    )
    def get(self, request):
        settings_obj = SystemSetting.load()
        return Response(SystemSettingSerializer(settings_obj).data)

    @extend_schema(
        summary="Update system settings",
        description="Partially update platform settings. Administrator (superuser) only.",
        request=SystemSettingSerializer,
        responses={200: SystemSettingSerializer},
        tags=["System"],
    )
    def patch(self, request):
        # Write requires elevated permissions
        if not request.user.is_superuser:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied()

        settings_obj = SystemSetting.load()
        serializer = SystemSettingSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
