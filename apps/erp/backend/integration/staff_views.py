"""Экран ERP «Интеграция с CRM» (M3-ERP-05): статус сопряжения (только чтение) и выпуск кода — только администратор.

Это internal API (`/api/v1/`, JWT сотрудника), не integration: сервисный токен CRM здесь ни при чём. Секреты наружу не
уходят — только состояние и последние 4 символа; код сопряжения виден один раз, в ответе на выпуск (`no-store`).
"""

from __future__ import annotations

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import log_admin_action
from core.permissions import ADMIN_ONLY, IsPlatformAdmin, RoleGatedViewMixin

from .services import credentials, pairing


class CrmPairingStatusSerializer(serializers.Serializer):
    state = serializers.ChoiceField(
        choices=["paired", "env", "none"],
        help_text="paired — сопряжено по коду; env — ключи из окружения (запасной путь); none — ключей нет.",
    )
    paired_at = serializers.DateTimeField(allow_null=True)
    rotated_at = serializers.DateTimeField(allow_null=True)
    token_source = serializers.ChoiceField(choices=["db", "env", "none"])
    crm_to_erp_last4 = serializers.CharField(allow_blank=True)
    previous_token_valid_until = serializers.DateTimeField(
        allow_null=True, help_text="Пока ротация не завершена: до какого срока ещё действует прежний токен CRM→ERP."
    )
    erp_to_crm_configured = serializers.BooleanField()
    webhook_secret_source = serializers.ChoiceField(choices=["db", "env", "none"])
    webhook_secret_last4 = serializers.CharField(allow_blank=True)
    code_ttl_seconds = serializers.IntegerField()
    crm_frontend_url = serializers.CharField(allow_blank=True)


class PairingCodeIssuedSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Одноразовый код сопряжения; показывается один раз.")
    expires_at = serializers.DateTimeField()
    ttl_seconds = serializers.IntegerField()


class CrmPairingStatusView(RoleGatedViewMixin, APIView):
    """GET /api/v1/integration/crm-pairing/ — состояние сопряжения (только администратор)."""

    required_permissions = {"GET": ADMIN_ONLY}
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    @extend_schema(
        summary="Состояние сопряжения с CRM",
        description="Только чтение. Значения ключей не возвращаются — состояние, источник и последние 4 символа.",
        responses={200: CrmPairingStatusSerializer},
        tags=["System"],
    )
    def get(self, request):
        st = credentials.status()
        data = {
            "state": st.state,
            "paired_at": st.paired_at,
            "rotated_at": st.rotated_at,
            "token_source": st.token_source,
            "crm_to_erp_last4": st.crm_to_erp_last4,
            "previous_token_valid_until": st.previous_token_valid_until,
            "erp_to_crm_configured": st.erp_to_crm_configured,
            "webhook_secret_source": st.webhook_secret_source,
            "webhook_secret_last4": st.webhook_secret_last4,
            "code_ttl_seconds": pairing.code_ttl_seconds(),
            "crm_frontend_url": settings.CRM_FRONTEND_URL,
        }
        return Response(CrmPairingStatusSerializer(data).data, headers={"Cache-Control": "no-store"})


class CrmPairingCodeView(RoleGatedViewMixin, APIView):
    """POST /api/v1/integration/crm-pairing/code/ — выпустить одноразовый код (прежний неиспользованный гаснет)."""

    required_permissions = {"POST": ADMIN_ONLY}
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    @extend_schema(
        summary="Выпустить код сопряжения с CRM",
        description=(
            "Администратор (superuser). Код одноразовый, действует `ttl_seconds`, виден только в этом ответе; "
            "в базе хранится хеш. Админ вводит его в CRM: «Подключения → ERP → Подключить ERP»."
        ),
        request=None,
        responses={200: PairingCodeIssuedSerializer},
        tags=["System"],
    )
    def post(self, request):
        issued = pairing.issue_code(created_by=request.user)
        # В аудит — только факт выпуска и срок; сам код (даже хвост) туда не попадает.
        log_admin_action(
            entity_type="crm_pairing",
            entity_id=0,
            action="Выпущен код сопряжения с CRM",
            detail=f"Действует до {issued.expires_at:%Y-%m-%d %H:%M} UTC",
            actor=request.user,
            event_code="integration.pairing_code_issued",
        )
        body = PairingCodeIssuedSerializer(
            {"code": issued.code, "expires_at": issued.expires_at, "ttl_seconds": issued.ttl_seconds}
        ).data
        return Response(body, headers={"Cache-Control": "no-store"})
