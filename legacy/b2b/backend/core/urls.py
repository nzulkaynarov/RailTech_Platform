from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from drf_spectacular.utils import extend_schema
from catalog.views import (
    ProductViewSet, EquipmentGroupViewSet, CategoryViewSet,
    ManufacturerViewSet, SupplierOfferViewSet, DomainTypeViewSet
)
from crm.views import (
    DealViewSet, QuoteViewSet, QuoteItemViewSet, MessageViewSet,
    LeadCreateView, CRMAnalyticsView, ActivityLogViewSet, DashboardAnalyticsView
)
from accounts.views import (
    CompanyViewSet, UserViewSet, RegisterView, SetupPasswordView, SubmitProfileView, MeView,
    SupplierSubscriptionViewSet, CompanyRoleApplicationViewSet,
)
from notifications.views import NotificationViewSet
from master_data.views import (
    CountryViewSet, CurrencyViewSet,
    UnitOfMeasureViewSet, DeliveryBasisViewSet
)
from sourcing.views import ExcelImportView, CatalogImportView, ImportStatusView, SourcingRequestViewSet
from core.health import health_check
from core.views import PageStatsView, SystemSettingsView

router = DefaultRouter()
router.register(r'catalog/products', ProductViewSet, basename='product')
router.register(r'catalog/offers', SupplierOfferViewSet, basename='offer')
router.register(r'catalog/equipment-groups', EquipmentGroupViewSet, basename='equipmentgroup')
router.register(r'catalog/categories', CategoryViewSet, basename='category')
router.register(r'catalog/manufacturers', ManufacturerViewSet, basename='manufacturer')
router.register(r'catalog/domain-types', DomainTypeViewSet, basename='domaintype')

router.register(r'crm/deals', DealViewSet, basename='deal')
router.register(r'crm/quotes', QuoteViewSet, basename='quote')
router.register(r'crm/quote-items', QuoteItemViewSet, basename='quoteitem')
router.register(r'crm/messages', MessageViewSet, basename='message')
router.register(r'crm/activity-logs', ActivityLogViewSet, basename='activitylog')

router.register(r'accounts/companies', CompanyViewSet)
router.register(r'accounts/users', UserViewSet)
router.register(r'accounts/subscriptions', SupplierSubscriptionViewSet, basename='subscription')
router.register(r'accounts/role-applications', CompanyRoleApplicationViewSet, basename='roleapplication')
router.register(r'notifications', NotificationViewSet, basename='notification')

# Master Data
router.register(r'master-data/countries', CountryViewSet)
router.register(r'master-data/currencies', CurrencyViewSet)
router.register(r'master-data/units', UnitOfMeasureViewSet)
router.register(r'master-data/delivery-basis', DeliveryBasisViewSet)

# Sourcing
router.register(r'sourcing/requests', SourcingRequestViewSet, basename='sourcing-request')

from accounts.wizard import CompanyWizardView, WIZARD_FORMS

urlpatterns = [
    path('admin/accounts/company/wizard/',
         CompanyWizardView.as_view(WIZARD_FORMS),
         name='company-wizard'),
    path('admin/', admin.site.urls),
    path('api/v1/', include(router.urls)),
    path('api/v1/auth/register/', RegisterView.as_view(), name='register'),
    path('api/v1/auth/setup-password/',
         SetupPasswordView.as_view(), name='setup-password'),
    path('api/v1/auth/submit-profile/',
         SubmitProfileView.as_view(), name='submit-profile'),
    path('api/v1/auth/token/',
         extend_schema(summary="Obtain JWT token pair", description="Authenticate with email and password to receive access and refresh tokens.", tags=['Auth'])(TokenObtainPairView).as_view(),
         name='token_obtain_pair'),
    path('api/v1/auth/token/refresh/',
         extend_schema(summary="Refresh JWT token", description="Exchange a valid refresh token for a new access token.", tags=['Auth'])(TokenRefreshView).as_view(),
         name='token_refresh'),
    # Sourcing & Imports
    path('api/v1/sourcing/import-deal/<int:deal_id>/', ExcelImportView.as_view(), name='import-deal'),
    path('api/v1/sourcing/import-catalog/', CatalogImportView.as_view(), name='import-catalog'),
    path('api/v1/sourcing/import-status/<str:task_id>/', ImportStatusView.as_view(), name='import-status'),
    path('api/v1/crm/analytics/', CRMAnalyticsView.as_view(), name='crm-analytics'),
    path('api/v1/crm/analytics/dashboard/', DashboardAnalyticsView.as_view(), name='dashboard-analytics'),
    path('api/v1/analytics/page-stats/', PageStatsView.as_view(), name='page-stats'),
    path('api/v1/crm/leads/', LeadCreateView.as_view(), name='lead-create'),
    path('api/v1/system-settings/', SystemSettingsView.as_view(), name='system-settings'),
    path('api/v1/accounts/me/', MeView.as_view(), name='current-user'),
    path('api/v1/health/', health_check, name='health_check'),
    # Root-level health endpoint for Docker/K8s healthchecks
    path('health/', health_check, name='health_check_root'),
    # API Documentation (drf-spectacular) — protected in production
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
] + ([
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
] if settings.DEBUG else []) + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
