import { Suspense, lazy, useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { AppShell } from './layouts/AppShell';
import { ErrorBoundary } from './components/Shared/ErrorBoundary';
import { FABSupportButton } from './components/Shared/FABSupportButton';
import { OnboardingTour } from './components/Shared/OnboardingTour';
import { PageBreadcrumb, getPageLabel } from './components/Shared/PageBreadcrumb';
import { useUserStore } from './store/userStore';
import { useAuthStore } from './store/authStore';
import { LoginPage } from './components/Auth/LoginPage';
import { KYCRegistrationForm } from './components/Auth/KYCRegistrationForm';
import { PasswordSetupPage } from './components/Auth/PasswordSetupPage';
import { ProfileCompletionForm } from './components/Cabinet/ProfileCompletionForm';

// Lazy load page components
const ProductManagement = lazy(() => import('./pages/ProductManagement').then(m => ({ default: m.ProductManagement })));
const ProductDetail = lazy(() => import('./pages/ProductDetail').then(m => ({ default: m.ProductDetail })));
const Dashboard = lazy(() => import('./pages/Dashboard').then(m => ({ default: m.Dashboard })));
const ProfilePage = lazy(() => import('./pages/ProfilePage').then(m => ({ default: m.ProfilePage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage })));
// OnboardingPage and PendingVerificationPage removed — real auth flow via LoginPage + KYCRegistrationForm
// Admin approves users via Django admin panel at /admin/
const RequestDetailPage = lazy(() => import('./pages/flow/RequestDetailPage').then(m => ({ default: m.RequestDetailPage })));
const PurchaseTemplatesPage = lazy(() => import('./pages/PurchaseTemplatesPage').then(m => ({ default: m.PurchaseTemplatesPage })));
const SourcingHub = lazy(() => import('./components/Sourcing/SourcingHub').then(m => ({ default: m.SourcingHub })));

// Lazy load individual page modules
const SourcingRequestsPage = lazy(() => import('./pages/SourcingRequestsPage'));
const SourcingImportPage = lazy(() => import('./pages/SourcingImportPage'));
const DealsPage = lazy(() => import('./pages/DealsPage'));
const QuotesPage = lazy(() => import('./pages/QuotesPage'));
const ClientsPage = lazy(() => import('./pages/ClientsPage'));
const ProductionOrdersPage = lazy(() => import('./pages/ProductionOrdersPage'));
const ProductionSchedulePage = lazy(() => import('./pages/ProductionSchedulePage'));
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'));
const CategoriesPage = lazy(() => import('./pages/CategoriesPage'));
const EquipmentGroupsPage = lazy(() => import('./pages/EquipmentGroupsPage'));
const IntegrationsPage = lazy(() => import('./pages/IntegrationsPage'));
const HelpPage = lazy(() => import('./pages/HelpPage'));
const MyRequestsPage = lazy(() => import('./pages/MyRequestsPage'));
const MyDocumentsPage = lazy(() => import('./pages/MyDocumentsPage'));
const LogisticsPage = lazy(() => import('./pages/LogisticsPage'));
const AdminUsersPage = lazy(() => import('./pages/AdminUsersPage'));

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

/** Parse URL path and query params for auth routes */
function useAuthRoute() {
  const [route, setRoute] = useState(() => {
    const url = new URL(window.location.href);
    const path = url.pathname;
    if (path === '/setup-password') {
      return {
        view: 'setup-password' as const,
        uid: url.searchParams.get('uid'),
        token: url.searchParams.get('token'),
      };
    }
    if (path === '/register') return { view: 'register' as const, uid: null, token: null };
    return { view: 'login' as const, uid: null, token: null };
  });

  const navigate = (view: 'login' | 'register') => {
    const newPath = view === 'register' ? '/register' : '/';
    window.history.pushState(null, '', newPath);
    setRoute({ view, uid: null, token: null });
  };

  // Handle browser back/forward
  useEffect(() => {
    const onPopState = () => {
      const url = new URL(window.location.href);
      const path = url.pathname;
      if (path === '/setup-password') {
        setRoute({
          view: 'setup-password',
          uid: url.searchParams.get('uid'),
          token: url.searchParams.get('token'),
        });
      } else if (path === '/register') {
        setRoute({ view: 'register', uid: null, token: null });
      } else {
        setRoute({ view: 'login', uid: null, token: null });
      }
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  return { route, navigate };
}

function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const initAuth = useAuthStore((s) => s.initAuth);
  const isLoading = useAuthStore((s) => s.isLoading);
  const loadFromAuth = useUserStore((s) => s.loadFromAuth);
  const { route, navigate } = useAuthRoute();
  const [profileCompleted, setProfileCompleted] = useState(false);

  // Initialize auth on app startup — validates persisted token
  useEffect(() => {
    initAuth();
  }, [initAuth]);

  // Sync userStore from authStore when authenticated
  useEffect(() => {
    if (isAuthenticated) {
      loadFromAuth();
      // Clear auth URL paths after login
      if (window.location.pathname !== '/') {
        window.history.replaceState(null, '', '/');
      }
    }
  }, [isAuthenticated, loadFromAuth]);

  if (isLoading) return <LoadingSkeleton />;

  // Password setup page — accessible without auth (from email link)
  if (route.view === 'setup-password') {
    return (
      <PasswordSetupPage
        uid={route.uid}
        token={route.token}
        onLogin={() => navigate('login')}
      />
    );
  }

  // Not authenticated — show login or registration
  if (!isAuthenticated) {
    if (route.view === 'register') {
      return <KYCRegistrationForm />;
    }
    return (
      <LoginPage
        onNavigate={() => {}}
        onRegister={() => navigate('register')}
      />
    );
  }

  // Authenticated but no company — show profile completion (company + type selection)
  const hasCompany = user?.company || user?.primary_company || profileCompleted;
  if (!hasCompany) {
    return (
      <ProfileCompletionForm
        onComplete={async () => {
          setProfileCompleted(true);
          await initAuth();
          await loadFromAuth();
        }}
      />
    );
  }

  return (
    <ErrorBoundary>
      <MainApp />
    </ErrorBoundary>
  );
}

function MainApp() {
  const { t } = useTranslation();
  const [page, setPage] = useState<Page>(() => {
    // Restore page from URL hash on initial load
    const hash = window.location.hash.replace('#', '');
    if (hash && hash !== 'dashboard') {
      return { type: hash } as Page;
    }
    return { type: 'dashboard' };
  });
  const [showTour, setShowTour] = useState(false);

  const navigateTo = (p: Page) => {
    setPage(p);
    // Sync URL hash with current page for browser back/forward
    const hash = p.type === 'product_detail' ? `product_detail/${(p as { productId: string }).productId}` : p.type;
    window.history.pushState({ page: p }, '', `#${hash}`);
  };

  // Handle browser back/forward
  useEffect(() => {
    const onPopState = (e: PopStateEvent) => {
      if (e.state?.page) {
        setPage(e.state.page);
      } else {
        const hash = window.location.hash.replace('#', '');
        if (hash) {
          setPage({ type: hash } as Page);
        } else {
          setPage({ type: 'dashboard' });
        }
      }
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

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
        { label: getPageLabel('products', t), pageId: 'products' },
        { label: t('breadcrumb.productDetail') },
      ];
      case 'request-detail': return [
        { label: getPageLabel('my-requests', t), pageId: 'my-requests' },
        { label: t('breadcrumb.requestDetail') },
      ];
      case 'sourcing-import': return [
        { label: getPageLabel('sourcing-requests', t), pageId: 'sourcing-requests' },
        { label: getPageLabel('sourcing-import', t) },
      ];
      case 'sourcing-match': return [
        { label: getPageLabel('sourcing-requests', t), pageId: 'sourcing-requests' },
        { label: getPageLabel('sourcing-match', t) },
      ];
      default: return [{ label: getPageLabel(page.type, t) }];
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
