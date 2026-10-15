from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as _serve_media
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from finance.views import DealMarginDeviationView, DealPurchaseActualDetailView, DealPurchaseActualsView
from rest_framework.permissions import IsAdminUser
from rest_framework.routers import DefaultRouter

from accounts.views import (
    CompanyRoleViewSet,
    CompanyTypeViewSet,
    CompanyViewSet,
    ContactViewSet,
    CookieTokenObtainPairView,
    CookieTokenRefreshView,
    ForgotPasswordView,
    LogoutView,
    MeView,
    PermissionCatalogView,
    ResetPasswordView,
    SessionListView,
    SessionsRevokeOthersView,
    SetupPasswordView,
    SystemRoleViewSet,
    TOTPDisableView,
    TOTPLoginView,
    TOTPSetupView,
    TOTPVerifyView,
    UserViewSet,
    WorkspaceRoleViewSet,
    WsTicketView,
)
from accounts.wizard import WIZARD_FORMS, CompanyWizardView
from catalog.views import (
    CategoryRequestViewSet,
    CategoryViewSet,
    DomainTypeViewSet,
    ManufacturerViewSet,
    ProductEnrichView,
    ProductStatusViewSet,
    ProductViewSet,
    StockStatusViewSet,
    SupplierOfferViewSet,
)
from core.health import health_check
from core.views import PageStatsView, PlatformDashboardView, SystemSettingsView
from crm.views import (
    ActivityLogViewSet,
    ActViewSet,
    ChargeTemplateViewSet,
    ChargeTypeViewSet,
    ContractViewSet,
    DashboardAnalyticsView,
    DealStageViewSet,
    DealViewSet,
    DocumentTemplateViewSet,
    FulfillmentViewSet,
    GeneratedDocumentViewSet,
    InvoiceViewSet,
    NumberingSchemePreviewView,
    NumberingSchemeView,
    PaymentViewSet,
    PublicDocumentView,
    PublicQuoteAcceptView,
    PublicQuotePageScriptView,
    PublicQuoteRejectView,
    PublicQuoteRequestCodeView,
    PublicQuoteView,
    PublicQuoteViewedView,
    QuoteChargeViewSet,
    QuoteItemViewSet,
    QuoteRequestDiffView,
    QuoteStatusViewSet,
    QuoteViewSet,
    RecentDocumentsView,
    SearchDocumentsView,
    TimelineView,
    TimeToFirstQuoteView,
    WordingVariantViewSet,
)
from master_data.views import (
    CountryViewSet,
    CurrencyViewSet,
    DeliveryBasisViewSet,
    UnitOfMeasureViewSet,
    hs_code_duties,
)
from notifications.views import EmailTemplateViewSet, NotificationViewSet
from sourcing.ai_jobs import AIJobStatusView
from sourcing.views import (  # noqa: F811
    AttachmentViewSet,
    CatalogImportView,
    CatalogTemplateView,
    DocumentExtractView,
    ExcelImportView,
    ImportCatalogAiView,
    ImportStatusView,
    MatchCatalogView,
    PreflightCheckView,
    QuoteImportFileView,
)
from sourcing.views_ai_conversational import ComposeRequestView  # noqa: E402,F811

router = DefaultRouter()
router.register(r"catalog/products", ProductViewSet, basename="product")
router.register(r"catalog/offers", SupplierOfferViewSet, basename="offer")
router.register(r"catalog/categories", CategoryViewSet, basename="category")
# Escape-hatch платформенной таксономии (R6): продавец ПРОСИТ категорию, а не заводит её.
router.register(r"catalog/category-requests", CategoryRequestViewSet, basename="categoryrequest")
router.register(r"catalog/manufacturers", ManufacturerViewSet, basename="manufacturer")
router.register(r"catalog/domain-types", DomainTypeViewSet, basename="domaintype")
router.register(r"catalog/product-statuses", ProductStatusViewSet, basename="productstatus")
router.register(r"catalog/stock-statuses", StockStatusViewSet, basename="stockstatus")

router.register(r"crm/deals", DealViewSet, basename="deal")
router.register(r"crm/quotes", QuoteViewSet, basename="quote")
router.register(r"crm/quote-items", QuoteItemViewSet, basename="quoteitem")
router.register(r"crm/quote-charges", QuoteChargeViewSet, basename="quotecharge")
router.register(r"crm/charge-types", ChargeTypeViewSet, basename="chargetype")
router.register(r"crm/charge-templates", ChargeTemplateViewSet, basename="chargetemplate")
router.register(r"crm/document-templates", DocumentTemplateViewSet, basename="documenttemplate")
router.register(r"crm/wording-variants", WordingVariantViewSet, basename="wordingvariant")
router.register(r"crm/generated-documents", GeneratedDocumentViewSet, basename="generateddocument")
router.register(r"crm/activity-logs", ActivityLogViewSet, basename="activitylog")
router.register(r"crm/deal-stages", DealStageViewSet, basename="dealstage")
router.register(r"crm/quote-statuses", QuoteStatusViewSet, basename="quotestatus")
router.register(r"crm/contracts", ContractViewSet, basename="contract")
router.register(r"crm/invoices", InvoiceViewSet, basename="invoice")
router.register(r"crm/payments", PaymentViewSet, basename="payment")
router.register(r"crm/acts", ActViewSet, basename="act")
router.register(r"crm/fulfillments", FulfillmentViewSet, basename="fulfillment")
# CRM Phase B — counterparty book (relationship edges of the user's own companies).

router.register(r"accounts/companies", CompanyViewSet)
# CRM Phase B — offline-client contacts (seller team's own book).
router.register(r"accounts/contacts", ContactViewSet, basename="contact")
router.register(r"accounts/users", UserViewSet)
router.register(r"accounts/system-roles", SystemRoleViewSet, basename="systemrole")
router.register(r"accounts/workspace-roles", WorkspaceRoleViewSet, basename="workspacerole")
router.register(r"accounts/company-types", CompanyTypeViewSet, basename="companytype")
router.register(r"accounts/company-roles", CompanyRoleViewSet, basename="company-role")
router.register(r"notifications", NotificationViewSet, basename="notification")
router.register(r"admin/email-templates", EmailTemplateViewSet, basename="admin-email-template")
router.register(r"settings/email-templates", EmailTemplateViewSet, basename="settings-email-template")

# Master Data
router.register(r"master-data/countries", CountryViewSet)
router.register(r"master-data/currencies", CurrencyViewSet)
router.register(r"master-data/units", UnitOfMeasureViewSet)
router.register(r"master-data/delivery-basis", DeliveryBasisViewSet)

# Sourcing
router.register(r"sourcing/attachments", AttachmentViewSet, basename="attachment")

urlpatterns = (
    [
        path("admin/accounts/company/wizard/", CompanyWizardView.as_view(WIZARD_FORMS), name="company-wizard"),
        path("admin/", admin.site.urls),
        path("api/v1/", include(router.urls)),
        path("api/portal/v1/", include("portal.urls")),
        path("api/v1/auth/setup-password/", SetupPasswordView.as_view(), name="setup-password"),
        path("api/v1/auth/forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
        path("api/v1/auth/reset-password/", ResetPasswordView.as_view(), name="reset-password"),
        path("api/v1/auth/logout/", LogoutView.as_view(), name="logout"),
        path("api/v1/auth/ws-ticket/", WsTicketView.as_view(), name="ws-ticket"),
        path(
            "api/v1/auth/token/",
            extend_schema(
                summary="Obtain JWT token pair",
                description="Authenticate with email and password to receive access and refresh tokens.",
                tags=["Auth"],
            )(CookieTokenObtainPairView).as_view(),
            name="token_obtain_pair",
        ),
        path(
            "api/v1/auth/token/refresh/",
            extend_schema(
                summary="Refresh JWT token",
                description="Exchange a valid refresh token for a new access token.",
                tags=["Auth"],
            )(CookieTokenRefreshView).as_view(),
            name="token_refresh",
        ),
        # Sessions live under /auth/ — the HttpOnly refresh cookie is path-scoped to
        # REFRESH_COOKIE_PATH and must reach these views (is_current / spare-current).
        path("api/v1/auth/sessions/", SessionListView.as_view(), name="auth-sessions"),
        path("api/v1/auth/sessions/revoke-all/", SessionsRevokeOthersView.as_view(), name="auth-sessions-revoke-all"),
        path("api/v1/auth/2fa/setup/", TOTPSetupView.as_view(), name="2fa-setup"),
        path("api/v1/auth/2fa/verify/", TOTPVerifyView.as_view(), name="2fa-verify"),
        path("api/v1/auth/2fa/disable/", TOTPDisableView.as_view(), name="2fa-disable"),
        path("api/v1/auth/login/2fa/", TOTPLoginView.as_view(), name="2fa-login"),
        # Sourcing & Imports
        path("api/v1/sourcing/import-deal/<int:deal_id>/", ExcelImportView.as_view(), name="import-deal"),
        path("api/v1/sourcing/match-catalog/", MatchCatalogView.as_view(), name="match-catalog"),
        path("api/v1/sourcing/preflight-check/", PreflightCheckView.as_view(), name="preflight-check"),
        path("api/v1/sourcing/extract-document/", DocumentExtractView.as_view(), name="extract-document"),
        path("api/v1/sourcing/import-quote-lines/", QuoteImportFileView.as_view(), name="import-quote-lines"),
        path("api/v1/sourcing/compose-request/", ComposeRequestView.as_view(), name="compose-request"),
        path("api/v1/catalog/product-enrich/", ProductEnrichView.as_view(), name="product-enrich"),
        path(
            "api/v1/crm/quotes/<int:quote_id>/request-diff/", QuoteRequestDiffView.as_view(), name="quote-request-diff"
        ),
        path("api/v1/sourcing/import-catalog/", CatalogImportView.as_view(), name="import-catalog"),
        path("api/v1/sourcing/import-catalog-ai/", ImportCatalogAiView.as_view(), name="import-catalog-ai"),
        path("api/v1/sourcing/catalog-template/", CatalogTemplateView.as_view(), name="catalog-template"),
        path("api/v1/sourcing/import-status/<str:task_id>/", ImportStatusView.as_view(), name="import-status"),
        # ARCH-01: polling endpoint for the off-thread AI jobs (202 + task_id pattern).
        path("api/v1/sourcing/ai-status/<str:task_id>/", AIJobStatusView.as_view(), name="ai-status"),
        # Витрина интегрированного тарифа ГТК: платежи по коду ТН ВЭД и стране происхождения.
        path("api/v1/master-data/hs-codes/<str:code>/duties/", hs_code_duties, name="hs-code-duties"),
        path("api/v1/crm/analytics/dashboard/", DashboardAnalyticsView.as_view(), name="dashboard-analytics"),
        path("api/v1/crm/analytics/time-to-first-quote/", TimeToFirstQuoteView.as_view(), name="time-to-first-quote"),
        path("api/v1/crm/analytics/recent-documents/", RecentDocumentsView.as_view(), name="recent-documents"),
        path("api/v1/crm/analytics/search-documents/", SearchDocumentsView.as_view(), name="search-documents"),
        # N2 — document-numbering-scheme editor (Settings → «Нумерация»). preview/ MUST
        # precede the bare path so it isn't shadowed.
        path(
            "api/v1/crm/numbering-scheme/preview/",
            NumberingSchemePreviewView.as_view(),
            name="numbering-scheme-preview",
        ),
        path("api/v1/crm/numbering-scheme/", NumberingSchemeView.as_view(), name="numbering-scheme"),
        # M1-ERP-08 — отклонение маржи сделки и факт закупки (вручную до M4).
        path(
            "api/v1/finance/deals/<int:deal_id>/margin-deviation/",
            DealMarginDeviationView.as_view(),
            name="deal-margin-deviation",
        ),
        path(
            "api/v1/finance/deals/<int:deal_id>/purchase-actuals/",
            DealPurchaseActualsView.as_view(),
            name="deal-purchase-actuals",
        ),
        path(
            "api/v1/finance/deals/<int:deal_id>/purchase-actuals/<str:currency>/",
            DealPurchaseActualDetailView.as_view(),
            name="deal-purchase-actual-detail",
        ),
        # CRM Phase A — counterparty / deal activity timeline (read-only).
        path("api/v1/crm/timeline/", TimelineView.as_view(), name="crm-timeline"),
        path("api/v1/analytics/page-stats/", PageStatsView.as_view(), name="page-stats"),
        path("api/v1/analytics/platform-dashboard/", PlatformDashboardView.as_view(), name="platform-dashboard"),
        # Public, unauthenticated КП surface by secret token (Wave A: page + offline acceptance).
        # The bare path content-negotiates (browser → HTML page, ?export=pdf → PDF); the action
        # endpoints (viewed beacon / request-code / accept / reject) are POST-only, JSON.
        # Tokenless, quote-agnostic page JS (served same-origin for CSP script-src 'self').
        path("api/v1/public/quote-page.js", PublicQuotePageScriptView.as_view(), name="public-quote-page-js"),
        path("api/v1/public/quotes/<str:token>/viewed/", PublicQuoteViewedView.as_view(), name="public-quote-viewed"),
        path(
            "api/v1/public/quotes/<str:token>/request-code/",
            PublicQuoteRequestCodeView.as_view(),
            name="public-quote-request-code",
        ),
        path("api/v1/public/quotes/<str:token>/accept/", PublicQuoteAcceptView.as_view(), name="public-quote-accept"),
        path("api/v1/public/quotes/<str:token>/reject/", PublicQuoteRejectView.as_view(), name="public-quote-reject"),
        path("api/v1/public/quotes/<str:token>/", PublicQuoteView.as_view(), name="public-quote"),
        # Public, unauthenticated ISSUED-document surface by secret token (II-1). Content-negotiates
        # (browser → HTML page, ?export=pdf → PDF, ARCH-03 202 pattern).
        path("api/v1/public/documents/<str:token>/", PublicDocumentView.as_view(), name="public-document"),
        path("api/v1/system-settings/", SystemSettingsView.as_view(), name="system-settings"),
        path("api/v1/accounts/me/", MeView.as_view(), name="current-user"),
        path("api/v1/accounts/permissions/", PermissionCatalogView.as_view(), name="permission-catalog"),
        path("api/v1/health/", health_check, name="health_check"),
        # Root-level health endpoint for Docker/K8s healthchecks
        path("health/", health_check, name="health_check_root"),
        # API Documentation (drf-spectacular) — the OpenAPI schema describes the
        # entire private API surface, so it must NOT be anonymously readable in
        # production (external HTTP study 2026-06-26 found api/schema/ public 200).
        # Gate it behind IsAdminUser: the SPA consumes the schema only at build
        # time (verified — no runtime fetch of /api/schema/ anywhere in
        # frontend/src), so requiring an authenticated staff user is safe.
        # docs/redoc below are already DEBUG-only.
        path(
            "api/schema/",
            SpectacularAPIView.as_view(permission_classes=[IsAdminUser]),
            name="schema",
        ),
    ]
    + (
        [
            path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
            path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
        ]
        if settings.DEBUG
        else []
    )
    # Serve PUBLIC media (avatars, logos, product images, category/manufacturer
    # assets) in production. When MinIO is disabled (VPS CPU lacks x86-64-v2,
    # see Docs/dev/ops/vps-cpu-constraints.md) storage falls back to FileSystemStorage,
    # but Django doesn't serve MEDIA with DEBUG=False — so uploads saved but never
    # displayed. This whitelists ONLY public display-asset prefixes; private files
    # (companies/*/documents, deals/**, sourcing/imports, temp)
    # never match and stay unreachable via /media (served only through auth views).
    + [
        re_path(
            r"^media/(?P<path>(?:users/\d+/avatar|companies/\d+/logo|manufacturers/\d+/logo"
            r"|products/\d+/images|categories/\d+/icon)/[^/]+)$",
            _serve_media,
            {"document_root": settings.MEDIA_ROOT},
            name="public-media",
        ),
    ]
    + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
)
