import { Suspense, useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { lazyWithRetry } from './lib/lazyWithRetry';
import { toast } from 'sonner';
import { AppShell } from './layouts/AppShell';
import { PlatformAdminShell } from './layouts/PlatformAdminShell';
import { ErrorBoundary } from './components/Shared/ErrorBoundary';
import { OnboardingTour } from './components/Shared/OnboardingTour';
import { PageBreadcrumb, getPageLabel } from './components/Shared/PageBreadcrumb';
import { useUserStore } from './store/userStore';
import { useAuthStore } from './store/authStore';
import { LoginPage } from './components/Auth/LoginPage';
import { KYCRegistrationForm } from './components/Auth/KYCRegistrationForm';
import { PasswordSetupPage } from './components/Auth/PasswordSetupPage';
import { ForgotPasswordPage } from './components/Auth/ForgotPasswordPage';
import { ResetPasswordPage } from './components/Auth/ResetPasswordPage';
import { ProfileCompletionForm } from './components/Cabinet/ProfileCompletionForm';

// Lazy load page components
const ProductManagement = lazyWithRetry(() => import('./pages/ProductManagement').then(m => ({ default: m.ProductManagement })));
const ProductDetail = lazyWithRetry(() => import('./pages/ProductDetail').then(m => ({ default: m.ProductDetail })));
const Dashboard = lazyWithRetry(() => import('./pages/Dashboard').then(m => ({ default: m.Dashboard })));
const ProfilePage = lazyWithRetry(() => import('./pages/ProfilePage').then(m => ({ default: m.ProfilePage })));
const SettingsPage = lazyWithRetry(() => import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage })));
// OnboardingPage and PendingVerificationPage removed — real auth flow via LoginPage + KYCRegistrationForm
// Admin approves users via Django admin panel at /admin/
const RequestDetailPage = lazyWithRetry(() => import('./pages/RequestDetailPage').then(m => ({ default: m.RequestDetailPage })));

// Lazy load individual page modules
const PlatformAdminDashboard = lazyWithRetry(() => import('./pages/PlatformAdminDashboard'));
const SourcingImportPage = lazyWithRetry(() => import('./pages/SourcingImportPage'));
const DealsPage = lazyWithRetry(() => import('./pages/DealsPage'));
const QuotesPage = lazyWithRetry(() => import('./pages/QuotesPage'));
const CategoriesPage = lazyWithRetry(() => import('./pages/CategoriesPage'));
const EquipmentGroupsPage = lazyWithRetry(() => import('./pages/EquipmentGroupsPage'));
const HelpPage = lazyWithRetry(() => import('./pages/HelpPage'));
const MyRequestsPage = lazyWithRetry(() => import('./pages/MyRequestsPage'));
const AdminUsersPage = lazyWithRetry(() => import('./pages/AdminUsersPage'));
const AdminKYCPage = lazyWithRetry(() => import('./pages/AdminKYCPage'));
const AdminSubscriptionsPage = lazyWithRetry(() => import('./pages/AdminSubscriptionsPage'));
const AdminEntitlementsPage = lazyWithRetry(() => import('./pages/AdminEntitlementsPage'));
const AdminRoleApplicationsPage = lazyWithRetry(() => import('./pages/AdminRoleApplicationsPage'));
const AdminCatalogPage = lazyWithRetry(() => import('./pages/AdminCatalogPage'));
const AdminCategoriesPage = lazyWithRetry(() => import('./pages/AdminCategoriesPage'));
const AdminEquipmentGroupsPage = lazyWithRetry(() => import('./pages/AdminEquipmentGroupsPage'));
const AdminOffersPage = lazyWithRetry(() => import('./pages/AdminOffersPage'));
const AdminCompaniesPage = lazyWithRetry(() => import('./pages/AdminCompaniesPage'));
const AdminDealsPage = lazyWithRetry(() => import('./pages/AdminDealsPage'));
const AdminMasterDataPage = lazyWithRetry(() => import('./pages/AdminMasterDataPage'));
const AdminEmailTemplatesPage = lazyWithRetry(() => import('./pages/AdminEmailTemplatesPage'));
const AdminOperatorRolesPage = lazyWithRetry(() => import('./pages/AdminOperatorRolesPage'));
const AdminAccessLogPage = lazyWithRetry(() => import('./pages/AdminAccessLogPage'));
const AdminSupportPage = lazyWithRetry(() => import('./pages/AdminSupportPage'));
const ContractsPage = lazyWithRetry(() => import('./pages/ContractsPage'));
const InvoicesPage = lazyWithRetry(() => import('./pages/InvoicesPage'));
const PaymentsPage = lazyWithRetry(() => import('./pages/PaymentsPage'));
const ActsPage = lazyWithRetry(() => import('./pages/ActsPage'));
const FulfillmentsPage = lazyWithRetry(() => import('./pages/FulfillmentsPage'));
const MySubscriptionPage = lazyWithRetry(() => import('./pages/MySubscriptionPage'));
const CatalogImportPage = lazyWithRetry(() => import('./pages/CatalogImportPage'));
const DealQuotePage = lazyWithRetry(() => import('./pages/DealQuotePage'));

import { LoadingSkeleton } from './components/LoadingSkeleton';

type Page =
  | { type: 'dashboard' }
  | { type: 'products' }
  | { type: 'request-detail'; dealId: number }
  | { type: 'product_detail'; productId: string }
  | { type: 'profile' }
  | { type: 'settings' }
  | { type: 'sourcing-requests' }
  | { type: 'sourcing-import' }
  | { type: 'crm-deals' }
  | { type: 'deal-quote'; dealId: number }
  | { type: 'crm-quotes' }
  | { type: 'categories' }
  | { type: 'equipment-groups' }
  | { type: 'help' }
  | { type: 'my-requests' }
  | { type: 'admin-users' }
  | { type: 'admin-kyc' }
  | { type: 'admin-subscriptions' }
  | { type: 'admin-entitlements' }
  | { type: 'admin-role-apps' }
  | { type: 'admin-catalog' }
  | { type: 'admin-categories' }
  | { type: 'admin-equipment-groups' }
  | { type: 'admin-offers' }
  | { type: 'admin-companies' }
  | { type: 'admin-deals' }
  | { type: 'admin-master-data' }
  | { type: 'admin-email-templates' }
  | { type: 'admin-operator-roles' }
  | { type: 'admin-access-log' }
  | { type: 'admin-support' }
  | { type: 'contracts' }
  | { type: 'invoices' }
  | { type: 'payments' }
  | { type: 'acts' }
  | { type: 'fulfillments' }
  | { type: 'my-subscription' }
  | { type: 'catalog-import' }
;

/** Parse URL path and query params for auth routes */
type AuthRouteView = 'login' | 'register' | 'setup-password' | 'forgot-password' | 'reset-password';

function parseAuthRoute(): { view: AuthRouteView; uid: string | null; token: string | null } {
  const url = new URL(window.location.href);
  const path = url.pathname;
  if (path === '/setup-password') {
    return {
      view: 'setup-password',
      uid: url.searchParams.get('uid'),
      token: url.searchParams.get('token'),
    };
  }
  if (path === '/reset-password') {
    return {
      view: 'reset-password',
      uid: url.searchParams.get('uid'),
      token: url.searchParams.get('token'),
    };
  }
  if (path === '/forgot-password') {
    return { view: 'forgot-password', uid: null, token: null };
  }
  if (path === '/register') {
    return { view: 'register', uid: null, token: null };
  }
  return { view: 'login', uid: null, token: null };
}

function useAuthRoute() {
  const [route, setRoute] = useState(parseAuthRoute);

  const navigate = (view: Extract<AuthRouteView, 'login' | 'register' | 'forgot-password'>) => {
    const pathMap: Record<typeof view, string> = {
      login: '/',
      register: '/register',
      'forgot-password': '/forgot-password',
    };
    window.history.pushState(null, '', pathMap[view]);
    setRoute({ view, uid: null, token: null });
  };

  // Handle browser back/forward
  useEffect(() => {
    const onPopState = () => setRoute(parseAuthRoute());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  return { route, navigate };
}

// Parse a URL hash back into a Page, restoring parameterised routes like
// `product_detail/<id>` so deep links / refresh / back-forward work.
function parseHashToPage(rawHash: string): Page {
  const hash = rawHash.replace(/^#/, '');
  // Drop any query suffix (e.g. `sourcing-import?deal=123`) — the target page reads
  // its own params from the hash; the page TYPE must be the bare route.
  const path = hash.split('?')[0];
  if (!path || path === 'dashboard') return { type: 'dashboard' };
  if (path.startsWith('product_detail/')) {
    return { type: 'product_detail', productId: path.slice('product_detail/'.length) } as Page;
  }
  if (path.startsWith('deal-quote/')) {
    const dealId = Number(path.slice('deal-quote/'.length));
    if (Number.isFinite(dealId) && dealId > 0) return { type: 'deal-quote', dealId };
    return { type: 'crm-deals' };
  }
  if (path === 'request-detail' || path.startsWith('request-detail/')) {
    const dealId = Number(path.slice('request-detail/'.length));
    if (Number.isFinite(dealId) && dealId > 0) return { type: 'request-detail', dealId };
    return { type: 'my-requests' };
  }
  return { type: path } as Page;
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
      // Don't rewrite the URL out from under a token-bearing public flow
      // (password setup/reset): a stale persisted session (isAuthenticated:true
      // in localStorage) must not hijack it. Mirrors the guard in api/client.ts.
      const onTokenFlow = route.view === 'setup-password' || route.view === 'reset-password';
      if (!onTokenFlow && window.location.pathname !== '/') {
        window.history.replaceState(null, '', '/');
      }
    }
  }, [isAuthenticated, loadFromAuth, route.view]);

  // Radix workaround: opening a Dialog (e.g. ConfirmActionDialog) from a
  // DropdownMenu/Select can leave document.body stuck at `pointer-events: none`
  // after both close, making the whole UI unclickable ("button doesn't react").
  // Clear it whenever NO modal layer (dialog/sheet/menu) remains open — open
  // Sheets/Dialogs keep their own lock, so this never breaks an active modal.
  useEffect(() => {
    const clearStuckPointerEvents = () => {
      if (document.body.style.pointerEvents !== 'none') return;
      const layerOpen = document.querySelector(
        '[data-state="open"][role="dialog"], [data-state="open"][role="menu"], [data-state="open"][role="listbox"]'
      );
      if (!layerOpen) document.body.style.pointerEvents = '';
    };
    const observer = new MutationObserver(clearStuckPointerEvents);
    observer.observe(document.body, { attributes: true, attributeFilter: ['style'] });
    return () => observer.disconnect();
  }, []);

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

  if (route.view === 'forgot-password') {
    return <ForgotPasswordPage onLogin={() => navigate('login')} />;
  }

  if (route.view === 'reset-password') {
    return (
      <ResetPasswordPage
        uid={route.uid}
        token={route.token}
        onLogin={() => navigate('login')}
        onForgot={() => navigate('forgot-password')}
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
        onForgotPassword={() => navigate('forgot-password')}
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
  'admin-users', 'admin-kyc', 'admin-subscriptions', 'admin-entitlements', 'admin-role-apps',
  'admin-catalog', 'admin-categories', 'admin-equipment-groups', 'admin-offers',
  'admin-companies', 'admin-deals', 'admin-master-data', 'admin-email-templates',
  'admin-operator-roles', 'admin-access-log', 'admin-support',
]);
const KYC_ALLOWED_PAGES = new Set(['dashboard', 'profile', 'settings', 'help']);

// Platform Admin is a viewer/moderator (ADR-0002): they reach moderation +
// platform-CRUD surfaces only, NEVER a buyer/seller business page (deals,
// quotes-as-a-seller, sourcing, my-requests, my-subscription…). This allowlist
// mirrors the admin sidebar (getAdminNavigation + bottom nav + footer profile);
// a non-allowlisted hash for an admin is bounced to the admin dashboard rather
// than rendering a business surface they must not act on.
const ADMIN_REACHABLE_PAGES = new Set([
  'dashboard', 'profile', 'settings', 'help',
  ...ADMIN_PAGES,
  // Moderation read surfaces the admin sidebar links to but which aren't
  // `admin-*` ids (force-approve quote / read-only contract inspection).
  'crm-quotes', 'contracts',
]);

// Role-scoped reachable pages. Closes "hidden" cross-role routes: a buyer
// hash-navigating to a seller page (crm-deals, deal-quote, analysis, sourcing…)
// is bounced to the dashboard instead of seeing seller/CRM UI. One standard for
// what each context can open — nav + deep links + back/forward all go through it.
const COMMON_PAGES = ['dashboard', 'profile', 'settings', 'help'];
const BUYER_PAGES = new Set([
  ...COMMON_PAGES,
  'products', 'product_detail', 'my-requests', 'request-detail',
  'contracts', 'invoices', 'payments', 'fulfillments', 'my-subscription',
]);
const SELLER_PAGES = new Set([
  ...COMMON_PAGES,
  'products', 'product_detail', 'categories', 'equipment-groups', 'catalog-import',
  'sourcing-requests', 'sourcing-import', 'crm-deals', 'crm-quotes',
  'deal-quote', 'request-detail', 'my-subscription',
  'contracts', 'invoices', 'payments', 'acts', 'fulfillments',
]);

function MainApp() {
  const { t } = useTranslation();
  const role = useUserStore((s) => s.role);
  const activeStatus = useUserStore((s) => s.activeStatus);
  const kycStatus = useUserStore((s) => s.company.kycStatus);
  const [page, setPage] = useState<Page>(() => parseHashToPage(window.location.hash));
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
      return;
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

  // Context guard: a buyer can't reach seller/CRM pages (and vice versa) even by
  // deep link — keeps each role to one coherent surface, no orphaned pages.
  // The platform admin (viewer) is gated to its own moderation allowlist so a
  // business page (deals, my-requests, sourcing…) never renders for them.
  useEffect(() => {
    if (role === 'ADMIN') {
      if (!ADMIN_REACHABLE_PAGES.has(page.type)) {
        toast.info(t('guards.notAvailableHere'));
        setPage({ type: 'dashboard' });
        window.history.replaceState(null, '', '#dashboard');
      }
      return;
    }
    const allowed = activeStatus === 'BUYER' ? BUYER_PAGES : SELLER_PAGES;
    if (!allowed.has(page.type)) {
      toast.info(t('guards.notAvailableHere'));
      setPage({ type: 'dashboard' });
      window.history.replaceState(null, '', '#dashboard');
    }
  }, [page.type, role, activeStatus, t]);

  // Handle browser back/forward
  useEffect(() => {
    const onPopState = (e: PopStateEvent) => {
      if (e.state?.page) {
        setPage(e.state.page);
      } else {
        setPage(parseHashToPage(window.location.hash));
      }
    };
    // Also react to direct `window.location.hash = …` assignments (used by a few
    // deep-links: cart→import, lead→deal, catalog bulk-import). Those fire
    // `hashchange`, not `popstate`, so without this listener the URL changed but
    // the page never switched — a silent dead-end.
    const onHashChange = () => setPage(parseHashToPage(window.location.hash));
    window.addEventListener('popstate', onPopState);
    window.addEventListener('hashchange', onHashChange);
    return () => {
      window.removeEventListener('popstate', onPopState);
      window.removeEventListener('hashchange', onHashChange);
    };
  }, []);

  const handleProductClick = (productId: string) => {
    navigateTo({ type: 'product_detail', productId });
  };

  const handleNavigate = (target: string) => {
    const validTypes = [
      'dashboard', 'products', 'profile', 'settings',
      'sourcing-requests', 'sourcing-import',
      'crm-deals', 'crm-quotes',
      'categories', 'equipment-groups',
      'help', 'my-requests',
      'admin-users', 'admin-kyc', 'admin-subscriptions', 'admin-entitlements', 'admin-role-apps',
      'admin-catalog', 'admin-categories', 'admin-equipment-groups', 'admin-offers',
      'admin-companies', 'admin-deals', 'admin-master-data', 'admin-email-templates',
      'admin-operator-roles', 'admin-access-log', 'admin-support',
      'contracts', 'invoices', 'payments', 'acts', 'fulfillments',
      'my-subscription', 'catalog-import',
    ];
    if (validTypes.includes(target)) {
      // Platform admin (viewer): only moderation/CRUD surfaces are reachable —
      // a business page target is bounced to the admin dashboard.
      if (role === 'ADMIN' && !ADMIN_REACHABLE_PAGES.has(target)) {
        toast.info(t('guards.notAvailableHere'));
        navigateTo({ type: 'dashboard' });
        return;
      }
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
        // The deal record is the seller's "Deals" detail and the buyer's "My Requests"
        // detail — one page, context-aware parent crumb.
        activeStatus === 'SELLER'
          ? { label: getPageLabel('crm-deals', t), pageId: 'crm-deals' }
          : { label: getPageLabel('my-requests', t), pageId: 'my-requests' },
        { label: t('breadcrumb.requestDetail') },
      ];
      case 'sourcing-import': return [
        { label: getPageLabel('crm-deals', t), pageId: 'crm-deals' },
        { label: getPageLabel('sourcing-import', t) },
      ];
      case 'deal-quote': return [
        { label: getPageLabel('crm-deals', t), pageId: 'crm-deals' },
        { label: t('pages.dealQuote.title') },
      ];
      default: return [{ label: getPageLabel(page.type, t) }];
    }
  };

  let content: React.ReactNode;
  let activePageId: string = page.type;

  switch (page.type) {
    case 'dashboard':
      content = role === 'ADMIN'
        ? <PlatformAdminDashboard onNavigate={handleNavigate} />
        : <Dashboard onProductClick={handleProductClick} onNavigate={handleNavigate} />;
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
          dealId={page.dealId}
          onBack={() => navigateTo({ type: activeStatus === 'SELLER' ? 'crm-deals' : 'my-requests' })}
        />
      );
      activePageId = activeStatus === 'SELLER' ? 'crm-deals' : 'my-requests';
      break;
    case 'sourcing-requests':
      // Consolidated into the single CRM → Deals pipeline. Keep the old hash route
      // working by rendering the canonical Deals surface (no separate page).
      content = <DealsPage />;
      activePageId = 'crm-deals';
      break;
    case 'sourcing-import':
      content = <SourcingImportPage />;
      break;
    case 'crm-deals':
      content = <DealsPage />;
      break;
    case 'deal-quote':
      // Same access surface as crm-deals (a seller working a КП). The backend
      // enforces seller-only writes on the quote/quote-item endpoints.
      content = <DealQuotePage dealId={page.dealId} onBack={() => navigateTo({ type: 'request-detail', dealId: page.dealId })} />;
      activePageId = 'crm-deals';
      break;
    case 'crm-quotes':
      content = <QuotesPage />;
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
      content = <MyRequestsPage />;
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
    case 'admin-entitlements':
      content = <AdminEntitlementsPage />;
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
    case 'admin-email-templates':
      content = <AdminEmailTemplatesPage />;
      break;
    case 'admin-operator-roles':
      content = <AdminOperatorRolesPage />;
      break;
    case 'admin-access-log':
      content = <AdminAccessLogPage />;
      break;
    case 'admin-support':
      content = <AdminSupportPage />;
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
    case 'my-subscription':
      content = <MySubscriptionPage />;
      break;
    case 'catalog-import':
      content = <CatalogImportPage />;
      break;
    default:
      // Unknown/stale hash → fall back to the role-correct dashboard (never show a
      // platform admin the buyer dashboard, as a raw default would).
      content = role === 'ADMIN'
        ? <PlatformAdminDashboard onNavigate={handleNavigate} />
        : <Dashboard onProductClick={handleProductClick} onNavigate={handleNavigate} />;
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
      <OnboardingTour
        open={showTour}
        onClose={() => setShowTour(false)}
        onNavigate={handleNavigate}
      />
    </AppShell>
  );
}

export default App;
