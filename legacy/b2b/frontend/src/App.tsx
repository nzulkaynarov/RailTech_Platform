import { Suspense, lazy, useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { AppShell } from './layouts/AppShell';
import { ErrorBoundary } from './components/Shared/ErrorBoundary';
import { FABSupportButton } from './components/Shared/FABSupportButton';
import { OnboardingTour } from './components/Shared/OnboardingTour';
import { PageBreadcrumb, getPageLabel } from './components/Shared/PageBreadcrumb';
import { useUserStore } from './store/userStore';
import { useAuthStore } from './store/authStore';

// Lazy load page components
const ProductManagement = lazy(() => import('./pages/ProductManagement').then(m => ({ default: m.ProductManagement })));
const ProductDetail = lazy(() => import('./pages/ProductDetail').then(m => ({ default: m.ProductDetail })));
const Dashboard = lazy(() => import('./pages/Dashboard').then(m => ({ default: m.Dashboard })));
const ProfilePage = lazy(() => import('./pages/ProfilePage').then(m => ({ default: m.ProfilePage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage })));
const OnboardingPage = lazy(() => import('./pages/OnboardingPage').then(m => ({ default: m.OnboardingPage })));
const PendingVerificationPage = lazy(() => import('./pages/PendingVerificationPage').then(m => ({ default: m.PendingVerificationPage })));
const RequestDetailPage = lazy(() => import('./pages/flow/RequestDetailPage').then(m => ({ default: m.RequestDetailPage })));
const PurchaseTemplatesPage = lazy(() => import('./pages/PurchaseTemplatesPage').then(m => ({ default: m.PurchaseTemplatesPage })));
const SourcingHub = lazy(() => import('./components/Sourcing/SourcingHub').then(m => ({ default: m.SourcingHub })));

// Lazy load placeholder pages
const SourcingRequestsPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.SourcingRequestsPage })));
const SourcingImportPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.SourcingImportPage })));
const DealsPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.DealsPage })));
const QuotesPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.QuotesPage })));
const ClientsPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.ClientsPage })));
const ProductionOrdersPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.ProductionOrdersPage })));
const ProductionSchedulePage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.ProductionSchedulePage })));
const AnalyticsPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.AnalyticsPage })));
const CategoriesPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.CategoriesPage })));
const EquipmentGroupsPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.EquipmentGroupsPage })));
const IntegrationsPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.IntegrationsPage })));
const HelpPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.HelpPage })));
const MyRequestsPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.MyRequestsPage })));
const MyDocumentsPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.MyDocumentsPage })));
const LogisticsPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.LogisticsPage })));
const AdminUsersPage = lazy(() => import('./pages/PlaceholderPages').then(m => ({ default: m.AdminUsersPage })));

import { LoadingSkeleton } from './components/LoadingSkeleton';

type Page =
  | { type: 'dashboard' }
  | { type: 'products' }
  | { type: 'request-detail' }
  | { type: 'product_detail'; productId: string }
  | { type: 'profile' }
  | { type: 'settings' }
  | { type: 'sourcing-requests' }
  | { type: 'sourcing-import' }
  | { type: 'sourcing-match' }
  | { type: 'crm-deals' }
  | { type: 'crm-quotes' }
  | { type: 'crm-clients' }
  | { type: 'production-orders' }
  | { type: 'production-schedule' }
  | { type: 'analytics' }
  | { type: 'categories' }
  | { type: 'equipment-groups' }
  | { type: 'integrations' }
  | { type: 'help' }
  | { type: 'my-requests' }
  | { type: 'my-documents' }
  | { type: 'admin-users' }
  | { type: 'logistics' }
  | { type: 'purchase-templates' };

function App() {
  const screen = useUserStore((s) => s.screen);
  const initAuth = useAuthStore((s) => s.initAuth);
  const isLoading = useAuthStore((s) => s.isLoading);

  // Initialize auth on app startup — validates persisted token
  useEffect(() => {
    initAuth();
  }, [initAuth]);

  if (isLoading) return <LoadingSkeleton />;

  if (screen === 'onboarding') return (
    <Suspense fallback={<LoadingSkeleton />}>
      <OnboardingPage />
    </Suspense>
  );

  if (screen === 'pending_verification') return (
    <Suspense fallback={<LoadingSkeleton />}>
      <PendingVerificationPage />
    </Suspense>
  );

  return (
    <ErrorBoundary>
      <MainApp />
    </ErrorBoundary>
  );
}

function MainApp() {
  const { t } = useTranslation();
  const [page, setPage] = useState<Page>({ type: 'dashboard' });
  const [showTour, setShowTour] = useState(false);

  const navigateTo = (p: Page) => setPage(p);

  const handleProductClick = (productId: string) => {
    navigateTo({ type: 'product_detail', productId });
  };

  const handleNavigate = (target: string) => {
    const validTypes = [
      'dashboard', 'products', 'profile', 'settings',
      'sourcing-requests', 'sourcing-import', 'sourcing-match',
      'crm-deals', 'crm-quotes', 'crm-clients',
      'production-orders', 'production-schedule',
      'analytics', 'categories', 'equipment-groups',
      'integrations', 'help', 'my-requests', 'my-documents',
      'admin-users', 'logistics', 'request-detail',
      'purchase-templates',
    ];
    if (validTypes.includes(target)) {
      navigateTo({ type: target } as Page);
    } else {
      navigateTo({ type: 'dashboard' });
    }
  };

  // Build breadcrumbs based on current page
  const getBreadcrumbs = () => {
    switch (page.type) {
      case 'dashboard': return [];
      case 'product_detail': return [
        { label: getPageLabel('products'), pageId: 'products' },
        { label: t('breadcrumb.productDetail') },
      ];
      case 'request-detail': return [
        { label: getPageLabel('my-requests'), pageId: 'my-requests' },
        { label: t('breadcrumb.requestDetail') },
      ];
      case 'sourcing-import': return [
        { label: getPageLabel('sourcing-requests'), pageId: 'sourcing-requests' },
        { label: getPageLabel('sourcing-import') },
      ];
      case 'sourcing-match': return [
        { label: getPageLabel('sourcing-requests'), pageId: 'sourcing-requests' },
        { label: 'Sourcing Hub' },
      ];
      default: return [{ label: getPageLabel(page.type) }];
    }
  };

  let content: React.ReactNode;
  let activePageId: string = page.type;

  switch (page.type) {
    case 'dashboard':
      content = <Dashboard onProductClick={handleProductClick} />;
      break;
    case 'product_detail':
      content = (
        <ProductDetail
          productId={page.productId}
          onBack={() => navigateTo({ type: 'products' })}
          onNavigate={(id) => navigateTo({ type: 'product_detail', productId: id })}
        />
      );
      activePageId = 'products';
      break;
    case 'products':
      content = <ProductManagement onProductClick={handleProductClick} />;
      break;
    case 'profile':
      content = <ProfilePage />;
      break;
    case 'settings':
      content = <SettingsPage />;
      break;
    case 'request-detail':
      content = (
        <RequestDetailPage
          onBack={() => navigateTo({ type: 'my-requests' })}
          onNavigate={handleNavigate}
        />
      );
      activePageId = 'my-requests';
      break;
    case 'sourcing-requests':
      content = <SourcingRequestsPage onNavigate={handleNavigate} />;
      break;
    case 'sourcing-import':
      content = <SourcingImportPage />;
      break;
    case 'sourcing-match':
      content = <SourcingHub />;
      activePageId = 'sourcing-match';
      break;
    case 'crm-deals':
      content = <DealsPage />;
      break;
    case 'crm-quotes':
      content = <QuotesPage />;
      break;
    case 'crm-clients':
      content = <ClientsPage />;
      break;
    case 'production-orders':
      content = <ProductionOrdersPage onNavigate={handleNavigate} />;
      break;
    case 'production-schedule':
      content = <ProductionSchedulePage />;
      break;
    case 'analytics':
      content = <AnalyticsPage />;
      break;
    case 'categories':
      content = <CategoriesPage />;
      break;
    case 'equipment-groups':
      content = <EquipmentGroupsPage />;
      break;
    case 'integrations':
      content = <IntegrationsPage />;
      break;
    case 'help':
      content = <HelpPage />;
      break;
    case 'my-requests':
      content = <MyRequestsPage onNavigate={handleNavigate} />;
      break;
    case 'my-documents':
      content = <MyDocumentsPage />;
      break;
    case 'admin-users':
      content = <AdminUsersPage />;
      break;
    case 'logistics':
      content = <LogisticsPage />;
      break;
    case 'purchase-templates':
      content = <PurchaseTemplatesPage />;
      break;
    default:
      content = <Dashboard onProductClick={handleProductClick} />;
      activePageId = 'dashboard';
  }

  const breadcrumbs = getBreadcrumbs();

  return (
    <AppShell activePage={activePageId} onNavigate={handleNavigate} onStartTour={() => setShowTour(true)}>
      <Suspense fallback={<LoadingSkeleton />}>
        {breadcrumbs.length > 0 && (
          <PageBreadcrumb segments={breadcrumbs} onNavigate={handleNavigate} />
        )}
        {content}
      </Suspense>
      <FABSupportButton />
      <OnboardingTour
        open={showTour}
        onClose={() => setShowTour(false)}
        onNavigate={handleNavigate}
      />
    </AppShell>
  );
}

export default App;
