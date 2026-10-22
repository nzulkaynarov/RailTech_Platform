"""Integration API Views (CRM → ERP, CONTRACTS §2, M3-ERP-01).

Реализация всех 12 эндпоинтов по спецификации packages/contracts/openapi/erp-integration.yaml:
- Сервисная аутентификация по Bearer SERVICE_TOKEN_CRM_TO_ERP
- Идемпотентность по заголовку Idempotency-Key
- Строгий формат ошибок {"detail": "<CODE>"}
- Клиентская проекция данных без внутренних закупочных цен, себестоимости и маржи
"""

from __future__ import annotations

import datetime
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import IntegrationTokenAuthentication
from .exceptions import (
    IntegrationConflict,
    IntegrationNotFound,
    IntegrationValidationError,
    integration_exception_handler,
)
from .idempotency import handle_idempotency
from .models import CrmContactMapping
from .serializers import (
    AiUsageRowSerializer,
    CatalogItemSerializer,
    CompanySummarySerializer,
    ContactInSerializer,
    ContactSerializer,
    DealListItemSerializer,
    DealSerializer,
    DocumentLinkSerializer,
    DocumentSerializer,
    ExternalSwitchInSerializer,
    ExternalSwitchStateSerializer,
    HandoffRequestSerializer,
    HandoffResponseSerializer,
    HealthSerializer,
    PairingAcceptedSerializer,
    PairingRequestSerializer,
    PairingRotatedSerializer,
    ProvisionUserRequestSerializer,
    ProvisionUserResponseSerializer,
)
from .services import bootstrap, pairing
from .services.catalog import search_published_catalog
from .services.handoff import process_client_handoff
from .services.provision import provision_crm_user, revoke_crm_user_sessions
from .services.summary import (
    get_company_summary_data,
    get_deal_detail_data,
    get_document_link_data,
    list_company_deals_data,
    list_deal_documents_data,
)
from .services.system import get_ai_usage_rows, get_system_health
from .throttles import IntegrationServiceRateThrottle, PairingAttemptThrottle

logger = logging.getLogger(__name__)


class BaseIntegrationView(APIView):
    """Базовый класс для всех интеграционных эндпоинтов CRM → ERP."""

    authentication_classes = [IntegrationTokenAuthentication]
    permission_classes = []
    # Свой лимит по токену CRM вместо общего anon 20/мин (Q-FIX30-4).
    throttle_classes = [IntegrationServiceRateThrottle]

    def get_exception_handler(self):
        return integration_exception_handler


class HandoffClientView(BaseIntegrationView):
    """POST /api/integration/v1/clients/handoff"""

    @handle_idempotency
    def post(self, request, *args, **kwargs):
        serializer = HandoffRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise IntegrationValidationError("VALIDATION_ERROR")

        response_data, created = process_client_handoff(serializer.validated_data)
        out_serializer = HandoffResponseSerializer(response_data)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(data=out_serializer.data, status=status_code)


class ContactDetailView(BaseIntegrationView):
    """PUT /api/integration/v1/contacts/{crm_contact_id}"""

    def put(self, request, crm_contact_id: int, *args, **kwargs):
        mapping = (
            CrmContactMapping.objects.filter(crm_contact_id=crm_contact_id).select_related("contact__company").first()
        )
        if not mapping or not mapping.contact:
            raise IntegrationNotFound("NOT_FOUND")

        serializer = ContactInSerializer(data=request.data)
        if not serializer.is_valid():
            raise IntegrationValidationError("VALIDATION_ERROR")

        data = serializer.validated_data
        contact = mapping.contact
        contact.name = data["name"].strip()
        contact.phone = (data.get("phone") or "").strip()
        contact.email = (data.get("email") or "").strip().lower()
        if "telegram_user_id" in data:
            contact.telegram_user_id = data.get("telegram_user_id")
        contact.language = data.get("language") or contact.language
        contact.is_primary = data.get("is_primary", contact.is_primary)
        contact.preferred_channel = data.get("preferred_channel", contact.preferred_channel)
        contact.save()

        contact_dict = {
            "crm_contact_id": crm_contact_id,
            "name": contact.name,
            "phone": contact.phone,
            "email": contact.email,
            "telegram_user_id": contact.telegram_user_id,
            "language": contact.language,
            "is_primary": contact.is_primary,
            "preferred_channel": contact.preferred_channel,
            "erp_contact_id": contact.id,
            "erp_company_id": contact.company_id,
            "cabinet_invited_at": contact.invited_at.isoformat() if contact.invited_at else None,
        }
        out_serializer = ContactSerializer(contact_dict)
        return Response(data=out_serializer.data, status=status.HTTP_200_OK)


class CompanySummaryView(BaseIntegrationView):
    """GET /api/integration/v1/companies/{erp_company_id}/summary"""

    def get(self, request, erp_company_id: int, *args, **kwargs):
        summary_data = get_company_summary_data(erp_company_id)
        if summary_data is None:
            raise IntegrationNotFound("NOT_FOUND")

        serializer = CompanySummarySerializer(summary_data)
        return Response(data=serializer.data, status=status.HTTP_200_OK)


class CompanyDealsView(BaseIntegrationView):
    """GET /api/integration/v1/companies/{erp_company_id}/deals"""

    def get(self, request, erp_company_id: int, *args, **kwargs):
        deals_data = list_company_deals_data(erp_company_id)
        if deals_data is None:
            raise IntegrationNotFound("NOT_FOUND")

        serializer = DealListItemSerializer(deals_data, many=True)
        return Response(data=serializer.data, status=status.HTTP_200_OK)


class DealDetailView(BaseIntegrationView):
    """GET /api/integration/v1/deals/{erp_deal_id}"""

    def get(self, request, erp_deal_id: int, *args, **kwargs):
        deal_data = get_deal_detail_data(erp_deal_id)
        if deal_data is None:
            raise IntegrationNotFound("NOT_FOUND")

        serializer = DealSerializer(deal_data)
        return Response(data=serializer.data, status=status.HTTP_200_OK)


class DealDocumentsView(BaseIntegrationView):
    """GET /api/integration/v1/deals/{erp_deal_id}/documents"""

    def get(self, request, erp_deal_id: int, *args, **kwargs):
        docs_data = list_deal_documents_data(erp_deal_id)
        if docs_data is None:
            raise IntegrationNotFound("NOT_FOUND")

        serializer = DocumentSerializer(docs_data, many=True)
        return Response(data=serializer.data, status=status.HTTP_200_OK)


class DocumentLinkView(BaseIntegrationView):
    """GET /api/integration/v1/documents/{erp_document_id}/link"""

    def get(self, request, erp_document_id: int, *args, **kwargs):
        crm_context = request.headers.get("X-CRM-Context") or request.META.get("HTTP_X_CRM_CONTEXT")
        link_data = get_document_link_data(erp_document_id, crm_context)
        if link_data is None:
            raise IntegrationNotFound("NOT_FOUND")

        serializer = DocumentLinkSerializer(link_data)
        return Response(data=serializer.data, status=status.HTTP_200_OK)


class CatalogSearchView(BaseIntegrationView):
    """GET /api/integration/v1/catalog/search"""

    def get(self, request, *args, **kwargs):
        q = request.query_params.get("q", "").strip()
        mode = request.query_params.get("mode", "").strip()
        limit_str = request.query_params.get("limit", "10")

        if not q or mode not in ("lead", "client"):
            raise IntegrationValidationError("VALIDATION_ERROR")

        try:
            limit = int(limit_str)
        except ValueError:
            raise IntegrationValidationError("VALIDATION_ERROR")

        items = search_published_catalog(query=q, mode=mode, limit=limit)
        serializer = CatalogItemSerializer(items, many=True)
        return Response(data=serializer.data, status=status.HTTP_200_OK)


class UserProvisionView(BaseIntegrationView):
    """POST /api/integration/v1/users/provision"""

    @handle_idempotency
    def post(self, request, *args, **kwargs):
        serializer = ProvisionUserRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise IntegrationValidationError("VALIDATION_ERROR")

        result, created = provision_crm_user(serializer.validated_data)
        out_serializer = ProvisionUserResponseSerializer(result)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(data=out_serializer.data, status=status_code)


class UserSessionsRevokeView(BaseIntegrationView):
    """DELETE /api/integration/v1/users/{crm_user_id}/sessions"""

    def delete(self, request, crm_user_id: int, *args, **kwargs):
        success = revoke_crm_user_sessions(crm_user_id)
        if not success:
            raise IntegrationNotFound("NOT_FOUND")
        return Response(status=status.HTTP_204_NO_CONTENT)


class AiUsageView(BaseIntegrationView):
    """GET /api/integration/v1/ai-usage"""

    def get(self, request, *args, **kwargs):
        date_from_str = request.query_params.get("date_from")
        date_to_str = request.query_params.get("date_to")

        if not date_from_str or not date_to_str:
            raise IntegrationValidationError("VALIDATION_ERROR")

        try:
            date_from = datetime.date.fromisoformat(date_from_str)
            date_to = datetime.date.fromisoformat(date_to_str)
        except ValueError:
            raise IntegrationValidationError("VALIDATION_ERROR")

        rows = get_ai_usage_rows(date_from, date_to)
        serializer = AiUsageRowSerializer(rows, many=True)
        return Response(data=serializer.data, status=status.HTTP_200_OK)


class IntegrationHealthView(BaseIntegrationView):
    """GET /api/integration/v1/health"""

    def get(self, request, *args, **kwargs):
        health_data, status_code = get_system_health()
        serializer = HealthSerializer(health_data)
        return Response(data=serializer.data, status=status_code)


def _pairing_body(request):
    serializer = PairingRequestSerializer(data=request.data)
    if not serializer.is_valid():
        raise IntegrationValidationError("VALIDATION_ERROR")
    return serializer.validated_data


def _audit_paired(request, method: str) -> None:
    """Запись в журнал ERP: сопряжено (способ, адрес CRM, версия), без кода, доказательства и ключей (ADR-0009)."""
    from core.audit import log_admin_action

    # Сопряжение уже закоммичено (секреты заменены, код погашен, окно закрыто): сбой журнала не должен превращать успех
    # в 500 — CRM повторила бы вызов с погашенным кодом и решила, что сопряжения нет. Пишем предупреждение без деталей.
    try:
        log_admin_action(
            entity_type="crm_pairing",
            entity_id=0,
            action="Сопряжено по bootstrap (без кода)" if method == "bootstrap" else "Сопряжено по коду из ERP",
            detail=f"Способ: {method}",
            actor=None,
            after={"method": method, "remote_addr": request.META.get("REMOTE_ADDR", "")},
            event_code="integration.paired_bootstrap" if method == "bootstrap" else "integration.paired_code",
        )
    except Exception as exc:  # noqa: BLE001 - аудит вторичен
        logger.warning("pairing audit entry (%s) was not written: %s", method, type(exc).__name__)


class PairingAcceptView(APIView):
    """POST /api/integration/v1/pairing/accept — аутентификация кодом сопряжения, а не сервисным токеном (M3-ERP-05)."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [PairingAttemptThrottle]

    def get_exception_handler(self):
        return integration_exception_handler

    def post(self, request, *args, **kwargs):
        raw_body = request.body  # до разбора: доказательство bootstrap покрывает хеш сырого тела
        proof = request.headers.get("X-Pairing-Proof")
        if proof is not None:
            return self._bootstrap(request, proof, raw_body)
        header = request.headers.get("Authorization", "").strip().split()
        # Код могли вставить с пробелами (`ABCD EFGH JKMN`): всё после схемы — код, нормализует сервис.
        code = "".join(header[1:]) if len(header) >= 2 and header[0].lower() == "bearer" else ""
        data = _pairing_body(request)
        result = pairing.accept(
            code,
            crm_to_erp_token=data["crm_to_erp_token"],
            erp_to_crm_token=data["erp_to_crm_token"],
            webhook_secret=data["webhook_secret"],
        )
        _audit_paired(request, "code")
        body = PairingAcceptedSerializer(
            {"paired": True, "paired_at": result.paired_at, "erp_version": getattr(settings, "ERP_VERSION", "0.1.0")}
        ).data
        return Response(data=body, status=status.HTTP_200_OK, headers={"Cache-Control": "no-store"})

    def _bootstrap(self, request, proof, raw_body):
        """Первое сопряжение без кода: доказательство владения общим секретом платформы (ADR-0009)."""
        bootstrap.verify(proof, raw_body)
        data = _pairing_body(request)
        result = pairing.accept_bootstrap(
            crm_to_erp_token=data["crm_to_erp_token"],
            erp_to_crm_token=data["erp_to_crm_token"],
            webhook_secret=data["webhook_secret"],
        )
        _audit_paired(request, "bootstrap")
        body = PairingAcceptedSerializer(
            {"paired": True, "paired_at": result.paired_at, "erp_version": getattr(settings, "ERP_VERSION", "0.1.0")}
        ).data
        return Response(data=body, status=status.HTTP_200_OK, headers={"Cache-Control": "no-store"})


class PairingRotateView(BaseIntegrationView):
    """POST /api/integration/v1/pairing/rotate — «Обновить ключи» без простоя (два активных токена)."""

    def post(self, request, *args, **kwargs):
        data = _pairing_body(request)
        result = pairing.rotate(
            request.auth,
            crm_to_erp_token=data["crm_to_erp_token"],
            erp_to_crm_token=data["erp_to_crm_token"],
            webhook_secret=data["webhook_secret"],
        )
        body = PairingRotatedSerializer(
            {
                "rotated": True,
                "rotated_at": result.rotated_at,
                "previous_token_valid_until": result.previous_token_valid_until,
            }
        ).data
        return Response(data=body, status=status.HTTP_200_OK, headers={"Cache-Control": "no-store"})


class ExternalSwitchView(BaseIntegrationView):
    """PUT /api/integration/v1/externals/{code}/switch (M3-ERP-06): выключатель внешнего сервиса ERP из CRM."""

    def put(self, request, code, *args, **kwargs):
        from core import external_status

        if code not in external_status.CODES:
            raise IntegrationNotFound()
        serializer = ExternalSwitchInSerializer(data=request.data)
        if not serializer.is_valid():
            raise IntegrationValidationError("VALIDATION_ERROR")
        try:
            row = external_status.set_enabled(
                code, serializer.validated_data["enabled"], serializer.validated_data.get("reason") or ""
            )
        except external_status.NotSwitchable:
            raise IntegrationConflict("NOT_SWITCHABLE")
        logger.info("integration: external service %s enabled=%s", code, row.enabled)
        return Response(
            data=ExternalSwitchStateSerializer(
                {"code": row.code, "enabled": row.enabled, "changed_at": row.changed_at}
            ).data,
            status=status.HTTP_200_OK,
        )
