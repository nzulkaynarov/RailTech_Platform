from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from finance.views import DealMarginDeviationView, DealPurchaseActualDetailView, DealPurchaseActualsView
from finance.views_receivables import (
    ReceivableBoardView,
    ReceivableCardView,
    ReceivableConfirmationFileView,
    ReceivableConfirmationsView,
    ReceivableConfirmPaymentView,
    ReceivableRequestPaymentDocView,
)
from integration.bus import get_bus
from integration.bus_journal_views import (
    BusDeliveriesView,
    BusDeliveryRetryView,
    BusInboxRetryView,
    BusInboxView,
    BusOverviewView,
    BusRetryDeadView,
)
from integration.public_views import PublicDocumentLinkView
from integration.staff_views import CrmPairingCodeView, CrmPairingStatusView
from inventory.views import (
    StockAdjustView,
    StockBalanceListView,
    StockProductView,
    StockReservationListView,
    StockReservationView,
    StockShipmentListView,
    StockSupplierListView,
)
from portal.exceptions import portal_not_found
from portal.public_views import (
    PublicDocumentView,
    PublicQuoteAcceptView,
    PublicQuotePageScriptView,
    PublicQuoteRejectView,
    PublicQuoteRequestCodeView,
    PublicQuoteView,
    PublicQuoteViewedView,
)
from rest_framework.permissions import IsAdminUser
from rest_framework.routers import DefaultRouter
from rt_bus.django.views import bus_view
from supply.views import (
    OrderCancelView,
    OrderConfirmView,
    OrderFromDealView,
    OrderListView,
    OrderReceiptView,
    OrderSendView,
    OrderView,
    OverdueListView,
    PriceRequestAnswerView,
    PriceRequestListView,
    ReceiptListView,
)

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
    SsoExchangeView,
    SsoIssueTokenView,
    SystemRoleViewSet,
    TOTPDisableView,
    TOTPLoginView,
    TOTPSetupView,
    TOTPVerifyView,
    UserViewSet,
    WorkspaceRoleViewSet,
    WsTicketView,
)
from accounts.views.setup import SetupCompanyView, SetupStatusView
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
from core.file_streaming import serve_public_media
from core.health import health_check
from core.views import (
    CurrentRateView,
    ExchangeRateJournalView,
    ManualRateView,
    PageStatsView,
    PlatformDashboardView,
    SystemSettingsView,
)
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
    ProjectDetailView,
    ProjectListView,
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
from crm.views.calc import (
    CalcCatalogView,
    CalcDealRefsView,
    CalcLinesView,
    CalcLineView,
    CalcLineVisaView,
    CalcParseView,
    CalcReadyView,
    CalcSheetView,
    CalcStartView,
    CalcTaskListView,
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
    QuoteImportFileView,
    QuoteParseRequestTextView,
)

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
        # D2-5: Все проекты — только чтение; пути раньше роутера, чтобы `crm/projects/<id>/` не искал вьюсет.
        path("api/v1/crm/projects/", ProjectListView.as_view(), name="project-list"),
        path("api/v1/crm/projects/<int:deal_id>/", ProjectDetailView.as_view(), name="project-detail"),
        path("api/v1/", include(router.urls)),
        path("api/portal/v1/", include("portal.urls")),
        re_path(r"^api/portal/", portal_not_found, name="portal-not-found"),  # FIX-54: JSON 404 вместо HTML Django
        path("api/integration/v1/", include("integration.urls")),
        # Приёмник шины rt_bus (B3): подпись HMAC v2, не JWT/сессия; снаружи закрыт Caddy (404), ходит только сеть compose.
        path("bus/v1/events", bus_view(get_bus), name="rt-bus-events"),
        path("api/v1/integration/crm-pairing/", CrmPairingStatusView.as_view(), name="crm-pairing-status"),
        path("api/v1/integration/crm-pairing/code/", CrmPairingCodeView.as_view(), name="crm-pairing-code"),
        # «Журнал интеграций» шины в Admin Платформы (W13-A2): чтение и повторы — team.manage или администратор.
        path("api/v1/integration/bus/overview/", BusOverviewView.as_view(), name="bus-overview"),
        path("api/v1/integration/bus/deliveries/", BusDeliveriesView.as_view(), name="bus-deliveries"),
        path("api/v1/integration/bus/deliveries/retry-dead/", BusRetryDeadView.as_view(), name="bus-retry-dead"),
        path(
            "api/v1/integration/bus/deliveries/<int:delivery_id>/retry/",
            BusDeliveryRetryView.as_view(),
            name="bus-delivery-retry",
        ),
        path("api/v1/integration/bus/inbox/", BusInboxView.as_view(), name="bus-inbox"),
        # id события — строкой: гейт права срабатывает раньше разбора UUID (неверный id — 400 после проверки права).
        path("api/v1/integration/bus/inbox/<str:event_id>/retry/", BusInboxRetryView.as_view(), name="bus-inbox-retry"),
        path("api/v1/auth/sso/token/", SsoIssueTokenView.as_view(), name="sso-token"),
        path("api/v1/auth/sso/exchange/", SsoExchangeView.as_view(), name="sso-exchange"),
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
                auth=[{}],  # вход без токена: в контракте не требует security (FIX-40)
            )(CookieTokenObtainPairView).as_view(),
            name="token_obtain_pair",
        ),
        path(
            "api/v1/auth/token/refresh/",
            extend_schema(
                summary="Refresh JWT token",
                description="Exchange a valid refresh token for a new access token.",
                tags=["Auth"],
                auth=[{}],  # refresh в HttpOnly-cookie, не bearer (FIX-40)
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
        path("api/v1/sourcing/extract-document/", DocumentExtractView.as_view(), name="extract-document"),
        path("api/v1/sourcing/import-quote-lines/", QuoteImportFileView.as_view(), name="import-quote-lines"),
        path(
            "api/v1/sourcing/parse-request-text/",
            QuoteParseRequestTextView.as_view(),
            name="parse-request-text",
        ),
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
        # D2-1 — «Расчёт по заявке» Платформы (crm.views.calc).
        path("api/v1/calc/tasks/", CalcTaskListView.as_view(), name="calc-tasks"),
        path("api/v1/calc/catalog/", CalcCatalogView.as_view(), name="calc-catalog"),
        path("api/v1/calc/deals/", CalcDealRefsView.as_view(), name="calc-deals"),
        path("api/v1/calc/<int:deal_id>/", CalcSheetView.as_view(), name="calc-sheet"),
        path("api/v1/calc/<int:deal_id>/start/", CalcStartView.as_view(), name="calc-start"),
        path("api/v1/calc/<int:deal_id>/lines/", CalcLinesView.as_view(), name="calc-lines"),
        path("api/v1/calc/<int:deal_id>/lines/<int:item_id>/", CalcLineView.as_view(), name="calc-line"),
        path("api/v1/calc/<int:deal_id>/lines/<int:item_id>/visa/", CalcLineVisaView.as_view(), name="calc-line-visa"),
        path("api/v1/calc/<int:deal_id>/ready/", CalcReadyView.as_view(), name="calc-ready"),
        path("api/v1/calc/<int:deal_id>/parse/", CalcParseView.as_view(), name="calc-parse"),
        # D2-2 — «Склад» Платформы: остатки, резервы, заказы поставщикам, приёмка, отгрузки, запросы цен.
        path("api/v1/stock/balances/", StockBalanceListView.as_view(), name="stock-balances"),
        path("api/v1/stock/balances/<int:product_id>/", StockProductView.as_view(), name="stock-product"),
        path("api/v1/stock/adjustments/", StockAdjustView.as_view(), name="stock-adjust"),
        path("api/v1/stock/reservations/", StockReservationListView.as_view(), name="stock-reservations"),
        path(
            "api/v1/stock/reservations/<int:reservation_id>/", StockReservationView.as_view(), name="stock-reservation"
        ),
        path("api/v1/stock/shipments/", StockShipmentListView.as_view(), name="stock-shipments"),
        path("api/v1/stock/suppliers/", StockSupplierListView.as_view(), name="stock-suppliers"),
        path("api/v1/stock/orders/", OrderListView.as_view(), name="stock-orders"),
        path("api/v1/stock/orders/from-deal/", OrderFromDealView.as_view(), name="stock-order-from-deal"),
        path("api/v1/stock/orders/<int:order_id>/", OrderView.as_view(), name="stock-order"),
        path("api/v1/stock/orders/<int:order_id>/send/", OrderSendView.as_view(), name="stock-order-send"),
        path("api/v1/stock/orders/<int:order_id>/confirm/", OrderConfirmView.as_view(), name="stock-order-confirm"),
        path("api/v1/stock/orders/<int:order_id>/cancel/", OrderCancelView.as_view(), name="stock-order-cancel"),
        path("api/v1/stock/orders/<int:order_id>/receipts/", OrderReceiptView.as_view(), name="stock-order-receive"),
        path("api/v1/stock/receipts/", ReceiptListView.as_view(), name="stock-receipts"),
        path("api/v1/stock/overdue/", OverdueListView.as_view(), name="stock-overdue"),
        path("api/v1/stock/price-requests/", PriceRequestListView.as_view(), name="stock-price-requests"),
        path(
            "api/v1/stock/price-requests/<int:request_id>/answer/",
            PriceRequestAnswerView.as_view(),
            name="stock-price-request-answer",
        ),
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
        # D2-4 — «Счета и оплаты» бухгалтера: доска по вкладкам, карточка, подтверждение оплаты, платёжка клиента.
        path("api/v1/finance/receivables/", ReceivableBoardView.as_view(), name="receivables-board"),
        path("api/v1/finance/receivables/<int:invoice_id>/", ReceivableCardView.as_view(), name="receivable-card"),
        path(
            "api/v1/finance/receivables/<int:invoice_id>/confirm-payment/",
            ReceivableConfirmPaymentView.as_view(),
            name="receivable-confirm-payment",
        ),
        path(
            "api/v1/finance/receivables/<int:invoice_id>/confirmations/",
            ReceivableConfirmationsView.as_view(),
            name="receivable-confirmations",
        ),
        path(
            "api/v1/finance/receivables/<int:invoice_id>/confirmations/<int:confirmation_id>/file/",
            ReceivableConfirmationFileView.as_view(),
            name="receivable-confirmation-file",
        ),
        path(
            "api/v1/finance/receivables/<int:invoice_id>/request-payment-doc/",
            ReceivableRequestPaymentDocView.as_view(),
            name="receivable-request-payment-doc",
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
        # Подписанная ссылка CRM на файл документа (FIX-32): токен выдаёт GET /api/integration/v1/documents/{id}/link.
        path(
            "api/v1/public/doc-links/<str:token>/",
            PublicDocumentLinkView.as_view(),
            name="public-document-link",
        ),
        path("api/v1/system-settings/", SystemSettingsView.as_view(), name="system-settings"),
        path("api/v1/exchange-rates/current/", CurrentRateView.as_view(), name="exchange-rate-current"),
        path("api/v1/exchange-rates/journal/", ExchangeRateJournalView.as_view(), name="exchange-rate-journal"),
        path("api/v1/exchange-rates/manual/", ManualRateView.as_view(), name="exchange-rate-manual"),
        path("api/v1/accounts/me/", MeView.as_view(), name="current-user"),
        path("api/v1/setup/status/", SetupStatusView.as_view(), name="setup-status"),
        path("api/v1/setup/company/", SetupCompanyView.as_view(), name="setup-company"),
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
    # Serve PUBLIC media (avatars, logos, product images, category/manufacturer assets): ERP reads them from the
    # `erp-public` bucket (RustFS is not exposed) and streams them; Caddy of the ERP and Cabinet domains routes
    # /media/* here. This whitelists ONLY public display-asset prefixes (the document-profile logo is public too: it is
    # printed on the КП/contract forms and shown in the cabinet); private files (companies/*/documents, products/*/docs,
    # deals/**, sourcing/imports, temp) never match and stay unreachable via /media (served only through auth views).
    + [
        re_path(
            r"^media/(?P<path>(?:users/\d+/avatar|companies/\d+/logo|companies/\d+/doc-profile/logo"
            r"|manufacturers/\d+/logo|products/\d+/images|categories/\d+/icon)/[^/]+)$",
            serve_public_media,
            name="public-media",
        ),
    ]
)
