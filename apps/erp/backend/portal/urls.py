"""URL configuration for the ERP Portal API (/api/portal/v1/*).

Strictly matches packages/contracts/openapi/erp-portal.yaml plus Q-14..Q-17 resolutions.
"""

from django.urls import path
from portal.views import (
    ActAcceptView,
    ActListView,
    ActReturnView,
    CatalogCategoriesView,
    CatalogDetailView,
    CatalogListView,
    CompanyView,
    ContractListView,
    ContractSignView,
    DeliveryListView,
    DocumentFileView,
    DocumentListView,
    InvoiceListView,
    LogoutView,
    MagicLinkExchangeView,
    MagicLinkRequestView,
    MeView,
    QuoteAcceptView,
    QuoteDetailView,
    QuoteListView,
    QuoteRejectView,
    RequestDetailView,
    RequestListView,
    TeamInviteView,
    TeamListView,
    TelegramAuthView,
    UploadView,
)

urlpatterns = [
    # Auth
    path("auth/telegram", TelegramAuthView.as_view(), name="portal-auth-telegram"),
    path("auth/telegram/", TelegramAuthView.as_view(), name="portal-auth-telegram-slash"),
    path("auth/magic-link", MagicLinkRequestView.as_view(), name="portal-auth-magic-link"),
    path("auth/magic-link/", MagicLinkRequestView.as_view(), name="portal-auth-magic-link-slash"),
    path("auth/magic/<str:token>", MagicLinkExchangeView.as_view(), name="portal-auth-magic-exchange"),
    path("auth/magic/<str:token>/", MagicLinkExchangeView.as_view(), name="portal-auth-magic-exchange-slash"),
    path("auth/logout", LogoutView.as_view(), name="portal-auth-logout"),
    path("auth/logout/", LogoutView.as_view(), name="portal-auth-logout-slash"),
    # Me
    path("me", MeView.as_view(), name="portal-me"),
    path("me/", MeView.as_view(), name="portal-me-slash"),
    # Requests (Запросы клиента)
    path("requests", RequestListView.as_view(), name="portal-requests"),
    path("requests/", RequestListView.as_view(), name="portal-requests-slash"),
    path("requests/<int:pk>", RequestDetailView.as_view(), name="portal-request-detail"),
    path("requests/<int:pk>/", RequestDetailView.as_view(), name="portal-request-detail-slash"),
    # Quotes (Коммерческие предложения)
    path("quotes", QuoteListView.as_view(), name="portal-quotes"),
    path("quotes/", QuoteListView.as_view(), name="portal-quotes-slash"),
    path("quotes/<int:pk>", QuoteDetailView.as_view(), name="portal-quote-detail"),
    path("quotes/<int:pk>/", QuoteDetailView.as_view(), name="portal-quote-detail-slash"),
    path("quotes/<int:pk>/accept", QuoteAcceptView.as_view(), name="portal-quote-accept"),
    path("quotes/<int:pk>/accept/", QuoteAcceptView.as_view(), name="portal-quote-accept-slash"),
    path("quotes/<int:pk>/reject", QuoteRejectView.as_view(), name="portal-quote-reject"),
    path("quotes/<int:pk>/reject/", QuoteRejectView.as_view(), name="portal-quote-reject-slash"),
    # Contracts (Договоры)
    path("contracts", ContractListView.as_view(), name="portal-contracts"),
    path("contracts/", ContractListView.as_view(), name="portal-contracts-slash"),
    path("contracts/<int:pk>/sign", ContractSignView.as_view(), name="portal-contract-sign"),
    path("contracts/<int:pk>/sign/", ContractSignView.as_view(), name="portal-contract-sign-slash"),
    # Invoices (Счета на оплату)
    path("invoices", InvoiceListView.as_view(), name="portal-invoices"),
    path("invoices/", InvoiceListView.as_view(), name="portal-invoices-slash"),
    # Acts (Акты)
    path("acts", ActListView.as_view(), name="portal-acts"),
    path("acts/", ActListView.as_view(), name="portal-acts-slash"),
    path("acts/<int:pk>/accept", ActAcceptView.as_view(), name="portal-act-accept"),
    path("acts/<int:pk>/accept/", ActAcceptView.as_view(), name="portal-act-accept-slash"),
    path("acts/<int:pk>/return", ActReturnView.as_view(), name="portal-act-return"),
    path("acts/<int:pk>/return/", ActReturnView.as_view(), name="portal-act-return-slash"),
    # Deliveries (Поставки)
    path("deliveries", DeliveryListView.as_view(), name="portal-deliveries"),
    path("deliveries/", DeliveryListView.as_view(), name="portal-deliveries-slash"),
    # Documents (Документы и файлы)
    path("documents", DocumentListView.as_view(), name="portal-documents"),
    path("documents/", DocumentListView.as_view(), name="portal-documents-slash"),
    path("documents/<int:pk>/file", DocumentFileView.as_view(), name="portal-document-file"),
    path("documents/<int:pk>/file/", DocumentFileView.as_view(), name="portal-document-file-slash"),
    # Uploads (Загрузка файлов, Q-14)
    path("uploads", UploadView.as_view(), name="portal-uploads"),
    path("uploads/", UploadView.as_view(), name="portal-uploads-slash"),
    # Catalog (Каталог продукции и категории, Q-15)
    path("catalog/categories", CatalogCategoriesView.as_view(), name="portal-catalog-categories"),
    path("catalog/categories/", CatalogCategoriesView.as_view(), name="portal-catalog-categories-slash"),
    path("catalog", CatalogListView.as_view(), name="portal-catalog"),
    path("catalog/", CatalogListView.as_view(), name="portal-catalog-slash"),
    path("catalog/<int:pk>", CatalogDetailView.as_view(), name="portal-catalog-detail"),
    path("catalog/<int:pk>/", CatalogDetailView.as_view(), name="portal-catalog-detail-slash"),
    # Company (Профиль компании)
    path("company", CompanyView.as_view(), name="portal-company"),
    path("company/", CompanyView.as_view(), name="portal-company-slash"),
    # Team (Команда клиента)
    path("team", TeamListView.as_view(), name="portal-team"),
    path("team/", TeamListView.as_view(), name="portal-team-slash"),
    path("team/invite", TeamInviteView.as_view(), name="portal-team-invite"),
    path("team/invite/", TeamInviteView.as_view(), name="portal-team-invite-slash"),
]
