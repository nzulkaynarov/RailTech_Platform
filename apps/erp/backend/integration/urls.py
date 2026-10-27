"""Integration URL patterns (CONTRACTS §0, §2, packages/contracts/openapi/erp-integration.yaml).

Все 16 интеграционных эндпоинтов направления CRM → ERP монтируются под `/api/integration/v1/`; сопряжение (M3-ERP-05) — `pairing/accept` и `pairing/rotate`.
"""

from django.urls import path

from .views import (
    AiUsageView,
    CatalogSearchView,
    ClientRequestView,
    CompanyDealsView,
    CompanySummaryView,
    ContactDetailView,
    DealDetailView,
    DealDocumentsView,
    DocumentLinkView,
    ExternalSwitchView,
    HandoffClientView,
    IntegrationHealthView,
    PairingAcceptView,
    PairingRotateView,
    UserProvisionView,
    UserSessionsRevokeView,
)

urlpatterns = [
    path("clients/handoff", HandoffClientView.as_view(), name="integration-clients-handoff"),
    path("clients/<int:crm_client_id>/requests", ClientRequestView.as_view(), name="integration-client-requests"),
    path("contacts/<int:crm_contact_id>", ContactDetailView.as_view(), name="integration-contact-detail"),
    path("companies/<int:erp_company_id>/summary", CompanySummaryView.as_view(), name="integration-company-summary"),
    path("companies/<int:erp_company_id>/deals", CompanyDealsView.as_view(), name="integration-company-deals"),
    path("deals/<int:erp_deal_id>", DealDetailView.as_view(), name="integration-deal-detail"),
    path("deals/<int:erp_deal_id>/documents", DealDocumentsView.as_view(), name="integration-deal-documents"),
    path("documents/<int:erp_document_id>/link", DocumentLinkView.as_view(), name="integration-document-link"),
    path("catalog/search", CatalogSearchView.as_view(), name="integration-catalog-search"),
    path("users/provision", UserProvisionView.as_view(), name="integration-user-provision"),
    path("users/<int:crm_user_id>/sessions", UserSessionsRevokeView.as_view(), name="integration-user-sessions-revoke"),
    path("ai-usage", AiUsageView.as_view(), name="integration-ai-usage"),
    path("health", IntegrationHealthView.as_view(), name="integration-health"),
    path("pairing/accept", PairingAcceptView.as_view(), name="integration-pairing-accept"),
    path("pairing/rotate", PairingRotateView.as_view(), name="integration-pairing-rotate"),
    path("externals/<str:code>/switch", ExternalSwitchView.as_view(), name="integration-external-switch"),
]
