import { Suspense, lazy, useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AppShell } from './layouts/AppShell';
import { PlatformAdminShell } from './layouts/PlatformAdminShell';
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
const SourcingHub = lazy(() => import('./components/Sourcing/SourcingHub').then(m => ({ default: m.SourcingHub })));

// Lazy load individual page modules
const SourcingRequestsPage = lazy(() => import('./pages/SourcingRequestsPage'));
const SourcingImportPage = lazy(() => import('./pages/SourcingImportPage'));
const DealsPage = lazy(() => import('./pages/DealsPage'));
const QuotesPage = lazy(() => import('./pages/QuotesPage'));
const ClientsPage = lazy(() => import('./pages/ClientsPage'));
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'));
const CategoriesPage = lazy(() => import('./pages/CategoriesPage'));
const EquipmentGroupsPage = lazy(() => import('./pages/EquipmentGroupsPage'));
const HelpPage = lazy(() => import('./pages/HelpPage'));
const MyRequestsPage = lazy(() => import('./pages/MyRequestsPage'));
const AdminUsersPage = lazy(() => import('./pages/AdminUsersPage'));
const AdminKYCPage = lazy(() => import('./pages/AdminKYCPage'));
const AdminSubscriptionsPage = lazy(() => import('./pages/AdminSubscriptionsPage'));
const AdminRoleApplicationsPage = lazy(() => import('./pages/AdminRoleApplicationsPage'));
const AdminCatalogPage = lazy(() => import('./pages/AdminCatalogPage'));
const AdminCategoriesPage = lazy(() => import('./pages/AdminCategoriesPage'));
const AdminEquipmentGroupsPage = lazy(() => import('./pages/AdminEquipmentGroupsPage'));
const AdminOffersPage = lazy(() => import('./pages/AdminOffersPage'));
const AdminCompaniesPage = lazy(() => import('./pages/AdminCompaniesPage'));
const AdminDealsPage = lazy(() => import('./pages/AdminDealsPage'));
const AdminMasterDataPage = lazy(() => import('./pages/AdminMasterDataPage'));
const ContractsPage = lazy(() => import('./pages/ContractsPage'));
const InvoicesPage = lazy(() => import('./pages/InvoicesPage'));
const PaymentsPage = lazy(() => import('./pages/PaymentsPage'));
const ActsPage = lazy(() => import('./pages/ActsPage'));
const FulfillmentsPage = lazy(() => import('./pages/FulfillmentsPage'));
const SupplierBidsPage = lazy(() => import('./pages/SupplierBidsPage'));
const LeadsPage = lazy(() => import('./pages/LeadsPage'));

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
  | { type: 'analytics' }
  | { type: 'categories' }
  | { type: 'equipment-groups' }
  | { type: 'help' }
  | { type: 'my-requests' }
  | { type: 'admin-users' }
  | { type: 'admin-kyc' }
  | { type: 'admin-subscriptions' }
  | { type: 'admin-role-apps' }
  | { type: 'admin-catalog' }
  | { type: 'admin-categories' }
  | { type: 'admin-equipment-groups' }
  | { type: 'admin-offers' }
  | { type: 'admin-companies' }
  | { type: 'admin-deals' }
  | { type: 'admin-master-data' }
  | { type: 'contracts' }
  | { type: 'invoices' }
  | { type: 'payments' }
  | { type: 'acts' }
  | { type: 'fulfillments' }
  | { type: 'supplier-bids' }
  | { type: 'leads' }
;

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

  // Initialize auth on app startup — validates persisted token and prefetches exchange rate in parallel
  useEffect(() => {
    initAuth();
    // Fire currency rate load in parallel — doesn't block UI
    import('./store/currencyStore').then(({ useCurrencyStore }) => {
      useCurrencyStore.getState().loadRate();
    });
  }, [initAuth]);

  // Sync userStore from authStore when authenticated
  useEffect(() => {
    if (isAuthenticated) {
      loadFromAuth();
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

  // Authenticated but no company — show profile completion (company + type selection).
  // Exception: platform admin (SystemRole.ADMIN) enters viewer mode and does NOT
  // need a company to moderate the platform.
  const hasCompany = user?.company || user?.primary_company || profileCompleted;
  const isPlatformAdmin = user?.role_code === 'ADMIN';
  if (!hasCompany && !isPlatformAdmin) {
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

const ADMIN_PAGES = new Set([
  'admin-users', 'admin-kyc', 'admin-subscriptions', 'admin-role-apps',
  'admin-catalog', 'admin-categories', 'admin-equipment-groups', 'admin-offers',
  'admin-companies', 'admin-deals', 'admin-master-data',
]);
// CRIT-2 / MED-18: pages that require manager-level RBAC but are not pure ADMIN.
// Accessible for ADMIN + MANAGER + SELLER (SELLER's CRM submenu exposes Leads).
// Leads — CRM-инструмент компании-продавца. Видимость регулируется по
// workspace-роли внутри компании, а не по системной роли платформы.
const KYC_ALLOWED_PAGES = new Set(['dashboard', 'profile', 'settings', 'help']);

function MainApp() {
  const { t } = useTranslation();
  const role = useUserStore((s) => s.role);
  const kycStatus = useUserStore((s) => s.company.kycStatus);
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

  // Role guard: redirect away from admin pages if not admin
  useEffect(() => {
    if (ADMIN_PAGES.has(page.type) && role !== 'ADMIN') {
      toast.error(t('guards.adminRequired'));
      setPage({ type: 'dashboard' });
      window.history.replaceState(null, '', '#dashboard');
    }
  }, [page.type, role, t]);

  // KYC guard: if not verified, only allow dashboard/profile/settings/help.
  // Platform admins are moderators, not business actors — their personal
  // company's KYC must not gate platform-admin navigation (see ADR-0002).
  useEffect(() => {
    if (role === 'ADMIN') return;
    if (kycStatus !== 'verified' && !KYC_ALLOWED_PAGES.has(page.type)) {
      // LOW-20: surface why the user was bounced back instead of silent redirect.
      toast.info(t('guards.kycRequired'));
      setPage({ type: 'dashboard' });
      window.history.replaceState(null, '', '#dashboard');
    }
  }, [page.type, kycStatus, role, t]);

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
      'analytics', 'categories', 'equipment-groups',
      'help', 'my-requests', 'request-detail',
      'admin-users', 'admin-kyc', 'admin-subscriptions', 'admin-role-apps',
      'admin-catalog', 'admin-categories', 'admin-equipment-groups', 'admin-offers',
      'admin-companies', 'admin-deals', 'admin-master-data',
      'contracts', 'invoices', 'payments', 'acts', 'fulfillments',
      'supplier-bids', 'leads',
    ];
    if (validTypes.includes(target)) {
      // Role guard: admin pages require ADMIN role
      if (ADMIN_PAGES.has(target) && role !== 'ADMIN') {
        toast.error(t('guards.adminRequired'));
        navigateTo({ type: 'dashboard' });
        return;
      }
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
      content = <Dashboard onProductClick={handleProductClick} onNavigate={handleNavigate} />;
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
    case 'analytics':
      content = <AnalyticsPage />;
      break;
    case 'categories':
      content = <CategoriesPage />;
      break;
    case 'equipment-groups':
      content = <EquipmentGroupsPage />;
      break;
    case 'help':
      content = <HelpPage />;
      break;
    case 'my-requests':
      content = <MyRequestsPage onNavigate={handleNavigate} />;
      break;
    case 'admin-users':
      content = <AdminUsersPage />;
      break;
    case 'admin-kyc':
      content = <AdminKYCPage />;
      break;
    case 'admin-subscriptions':
      content = <AdminSubscriptionsPage />;
      break;
    case 'admin-role-apps':
      content = <AdminRoleApplicationsPage />;
      break;
    case 'admin-catalog':
      content = <AdminCatalogPage />;
      break;
    case 'admin-categories':
      content = <AdminCategoriesPage />;
      break;
    case 'admin-equipment-groups':
      content = <AdminEquipmentGroupsPage />;
      break;
    case 'admin-offers':
      content = <AdminOffersPage />;
      break;
    case 'admin-companies':
      content = <AdminCompaniesPage />;
      break;
    case 'admin-deals':
      content = <AdminDealsPage />;
      break;
    case 'admin-master-data':
      content = <AdminMasterDataPage />;
      break;
    case 'contracts':
      content = <ContractsPage />;
      break;
    case 'invoices':
      content = <InvoicesPage />;
      break;
    case 'payments':
      content = <PaymentsPage />;
      break;
    case 'acts':
      content = <ActsPage />;
      break;
    case 'fulfillments':
      content = <FulfillmentsPage />;
      break;
    case 'supplier-bids':
      content = <SupplierBidsPage />;
      break;
    case 'leads':
      content = <LeadsPage />;
      break;
    default:
      content = <Dashboard onProductClick={handleProductClick} onNavigate={handleNavigate} />;
      activePageId = 'dashboard';
  }

  const breadcrumbs = getBreadcrumbs();
  const isPlatformAdmin = useUserStore((s) => s.role === 'ADMIN');

  if (isPlatformAdmin) {
    return (
      <PlatformAdminShell activePage={activePageId} onNavigate={handleNavigate}>
        <Suspense fallback={<LoadingSkeleton />}>
          {breadcrumbs.length > 0 && (
            <PageBreadcrumb segments={breadcrumbs} onNavigate={handleNavigate} />
          )}
          {content}
        </Suspense>
      </PlatformAdminShell>
    );
  }

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
