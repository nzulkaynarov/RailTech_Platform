from django.conf import settings as django_settings
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import SystemSetting
from core.permissions import IsPlatformAdmin, RoleGatedViewMixin

# ──────────────────────────────────────────────────────────────────────────
# System Settings (singleton)
# ──────────────────────────────────────────────────────────────────────────

#: Общие для ансамбля поля (FIX-42, F-4): ведутся в CRM, в ERP — только просмотр. Запись — 400 с этим кодом.
SHARED_FIELDS = ("domain", "logo_url", "platform_name", "support_email")
SHARED_FIELD_READ_ONLY = "SHARED_SETTING_READ_ONLY"


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

    crm_frontend_url = drf_serializers.SerializerMethodField(
        help_text="Адрес CRM: туда ведёт «Изменить в CRM» для общих полей, только чтение."
    )

    def get_crm_frontend_url(self, obj) -> str:
        return django_settings.CRM_FRONTEND_URL

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
            "crm_frontend_url",
            "maintenance_mode",
            "is_two_factor_required",
            "updated_at",
        ]
        read_only_fields = [*SHARED_FIELDS, "updated_at"]


class SystemSettingsView(RoleGatedViewMixin, APIView):
    """
    GET  /api/v1/system-settings/ — read current settings (any authenticated user)
    PATCH /api/v1/system-settings/ — update settings: `vat_rate` — право `settings.edit` (раздел Платформы «Компания»,
    W13-A3) или администратор; остальные поля (`maintenance_mode`, `is_two_factor_required`) — только администратор
    (`is_superuser`): они закрывают вход всем.
    """

    required_permissions = {
        "PATCH": "settings.edit",
        "PUT": "settings.edit",
    }

    #: Поля, которые вправе менять не администратор, а держатель `settings.edit`.
    COMPANY_EDITABLE = frozenset({"vat_rate"})

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
        description=(
            "Partially update platform settings. `vat_rate` — `settings.edit` or administrator; "
            "`maintenance_mode` and `is_two_factor_required` — administrator (superuser) only. "
            "`platform_name`, `support_email`, `logo_url` and `domain` are shared by the whole ensemble and "
            "managed in CRM: a request that contains any of them is rejected with 400 `SHARED_SETTING_READ_ONLY`."
        ),
        request=SystemSettingSerializer,
        responses={
            200: SystemSettingSerializer,
            400: OpenApiResponse(
                response=inline_serializer(
                    "SharedSettingReadOnlyError",
                    fields={
                        "detail": drf_serializers.CharField(),
                        "fields": drf_serializers.ListField(child=drf_serializers.CharField()),
                    },
                ),
                description="SHARED_SETTING_READ_ONLY (`fields` names the rejected shared fields) or serializer field errors",
            ),
        },
        tags=["System"],
    )
    def patch(self, request):
        # Держатель `settings.edit` (гейт выше) меняет только ставку НДС; остальное — администратор.
        if not request.user.is_superuser and not set(request.data) <= self.COMPANY_EDITABLE:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(detail=IsPlatformAdmin.message, code=IsPlatformAdmin.message)

        # Общие поля ведёт CRM. Молча отбросить их нельзя: старый клиент увидел бы «сохранено» и решил бы, что
        # имя поменялось. Тело с такими полями отвергается целиком — частичное применение хуже отказа.
        shared = sorted(name for name in SHARED_FIELDS if name in request.data)
        if shared:
            return Response({"detail": SHARED_FIELD_READ_ONLY, "fields": shared}, status=400)

        settings_obj = SystemSetting.load()
        serializer = SystemSettingSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
