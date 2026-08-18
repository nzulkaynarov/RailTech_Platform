import { Suspense, useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AppShell } from './layouts/AppShell';
import { PlatformAdminShell } from './layouts/PlatformAdminShell';
import { ErrorBoundary } from './components/Shared/ErrorBoundary';
import { OnboardingTour } from './components/Shared/OnboardingTour';
import { PageBreadcrumb } from './components/Shared/PageBreadcrumb';
import { getPageLabel } from '@/lib/pageLabels';
import { useUserStore } from './store/userStore';
import { useAuthStore } from './store/authStore';
import { LoginPage } from './components/Auth/LoginPage';
import { KYCRegistrationForm } from './components/Auth/KYCRegistrationForm';
import { PasswordSetupPage } from './components/Auth/PasswordSetupPage';
import { ForgotPasswordPage } from './components/Auth/ForgotPasswordPage';
import { ResetPasswordPage } from './components/Auth/ResetPasswordPage';
import { ProfileCompletionForm } from './components/Cabinet/ProfileCompletionForm';
import { LoadingSkeleton } from './components/LoadingSkeleton';
import { NAVIGABLE_PAGES } from './config/pageRegistry';
import { parseHashToPage, pageToHash, type Page } from './routes/hashRoute';
import { evaluatePageGuard } from './routes/pageGuard';
import { renderPage } from './routes/pageContent';

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
    // CRM Phase D — a CB-invite link (/register?invite=…) claims an existing offline company.
    // Stash the token so it survives the register → setup-password → submit-profile steps.
    const invite = url.searchParams.get('invite');
    if (invite) sessionStorage.setItem('cb_invite_token', invite);
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

function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const initAuth = useAuthStore((s) => s.initAuth);
  const loadFromAuth = useUserStore((s) => s.loadFromAuth);
  const { route, navigate } = useAuthRoute();
  const [profileCompleted, setProfileCompleted] = useState(false);
  // Full-page skeleton is for the INITIAL cold-load session check ONLY. It must NOT
  // key off the store's `isLoading`, which also spikes during an interactive login()/
  // login2FA() call — that would unmount LoginPage mid-login and wipe its local state
  // (twoFactorRequired/tempToken/serverError), so a 2FA-enabled user could never reach
  // the code-entry step. The login button has its own spinner (reads store.isLoading).
  const [initializing, setInitializing] = useState(true);

  // Initialize auth on app startup — validates persisted token and prefetches exchange rate in parallel
  useEffect(() => {
    initAuth().finally(() => setInitializing(false));
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

  if (initializing) return <LoadingSkeleton />;

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

function MainApp() {
  const { t } = useTranslation();
  const role = useUserStore((s) => s.role);
  const activeStatus = useUserStore((s) => s.activeStatus);
  const setActiveStatus = useUserStore((s) => s.setActiveStatus);
  const statusEntries = useUserStore((s) => s.company.statusEntries);
  const kycStatus = useUserStore((s) => s.company.kycStatus);
  // `screen` flips to 'main' only when loadFromAuth() has populated real
  // capabilities. Guards are deferred until then (see evaluatePageGuard) so a
  // cold-load deep-link isn't bounced by pre-auth default state.
  const bootstrapped = useUserStore((s) => s.screen === 'main');
  const queryClient = useQueryClient();
  const [page, setPage] = useState<Page>(() => parseHashToPage(window.location.hash));
  const [showTour, setShowTour] = useState(false);

  const navigateTo = (p: Page) => {
    setPage(p);
    // Sync URL hash with current page for browser back/forward
    window.history.pushState({ page: p }, '', `#${pageToHash(p)}`);
  };

  // Unified page-access guard (role → KYC → context), driven by the pure
  // evaluatePageGuard. DEFERRED until userStore bootstrap (`bootstrapped`,
  // i.e. screen === 'main'): on a cold deep-link the store still holds pre-auth
  // defaults, and enforcing then would bounce a valid hash to #dashboard and
  // clobber it via replaceState. Once loadFromAuth resolves real capabilities the
  // effect re-runs (deps below) and enforces exactly as before —
  //   • non-admin on an admin-* page → toast.error(adminRequired) → dashboard;
  //   • platform admin off its allowlist → toast.info(notAvailableHere) → dashboard;
  //   • unverified user off the KYC floor → toast.info(kycRequired) → dashboard;
  //   • page unique to the user's OTHER verified context → adopt it (+ refetch);
  //   • cross-role page (buyer→seller-only etc.) → toast.info(notAvailableHere) → dashboard.
  useEffect(() => {
    const decision = evaluatePageGuard({
      pageType: page.type,
      role,
      kycStatus,
      activeStatus,
      statusEntries,
      bootstrapped,
    });
    if (decision.action === 'allow') return;
    if (decision.action === 'adopt') {
      // Phase C page-derived context: the working context follows the page.
      // Invalidate queries so the new context refetches (mirrors the manual switcher).
      setActiveStatus(decision.context);
      queryClient.invalidateQueries();
      return;
    }
    // decision.action === 'bounce' — surface WHY, then fall back to the dashboard.
    if (decision.reason === 'admin') {
      toast.error(t('guards.adminRequired'));
    } else if (decision.reason === 'kyc') {
      // LOW-20: surface why the user was bounced back instead of silent redirect.
      toast.info(t('guards.kycRequired'));
    } else {
      toast.info(t('guards.notAvailableHere'));
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- гейт страницы: не синхронизация, а НАВИГАЦИЯ с побочными действиями (toast + history.replaceState)
    setPage({ type: 'dashboard' });
    window.history.replaceState(null, '', '#dashboard');
  }, [page.type, role, kycStatus, activeStatus, statusEntries, bootstrapped, setActiveStatus, queryClient, t]);

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

  // Legacy-алиас (settings-profile-redesign §2.1): `#profile` — рабочий deep-link на
  // Settings Hub с секцией profile. Нормализуем URL в канонический вид
  // `?section=profile` + `#settings` (useUrlState читает search-часть, не hash-query),
  // replaceState — чтобы back/forward не возвращали на промежуточный `#profile`.
  useEffect(() => {
    if (page.type !== 'profile') return;
    const params = new URLSearchParams(window.location.search);
    params.set('section', 'profile');
    window.history.replaceState(
      { page: { type: 'settings' } },
      '',
      `${window.location.pathname}?${params.toString()}#settings`,
    );
    // eslint-disable-next-line react-hooks/set-state-in-effect -- нормализация legacy-URL `#profile`: пишет в history, то есть работает с внешней системой
    setPage({ type: 'settings' });
  }, [page.type]);

  const handleProductClick = (productId: string) => {
    navigateTo({ type: 'product_detail', productId });
  };

  const handleNavigate = (target: string) => {
    // Параметрные цели из страниц («product-edit/42»): NAVIGABLE_PAGES хранит голые
    // идентификаторы, и без этой ветки переход в редактор молча отскакивал на дашборд —
    // поймано проходом глазами: «Дополнить» из реестра вела в никуда.
    if (target.startsWith('product-edit/')) {
      const productId = target.slice('product-edit/'.length);
      const decision = evaluatePageGuard({
        pageType: 'product-edit', role, kycStatus, activeStatus, statusEntries, bootstrapped,
      });
      if (decision.action !== 'bounce' && productId) {
        navigateTo({ type: 'product-edit', productId });
        return;
      }
    }
    // Цели меню — из реестра страниц (`navigable`). Раньше здесь лежал четвёртый
    // рукописный список идентификаторов, и он уже расходился с остальными: пункты
    // «Клиенты»/«Поставщики» существовали и в рендере, и в наборах контекста, но
    // отсутствовали ЗДЕСЬ — клик по ним молча уводил на дашборд (ADR-0005 Phase F).
    if (!NAVIGABLE_PAGES.has(target)) {
      navigateTo({ type: 'dashboard' });
      return;
    }
    // Решение о доступе — ТОТ ЖЕ `evaluatePageGuard`, что и у эффекта ниже. Раньше здесь
    // проверялись только роль и админский список, а гейты KYC и контекста доставались уже
    // ПОСЛЕ перехода: страница успевала смонтироваться и отскакивала — пользователь видел
    // мигание вместо отказа (аудит UI 2026-07-30). Теперь отказ виден до навигации, причина
    // формулируется один раз, а `adopt` (страница другого подтверждённого контекста) как и
    // прежде пропускается вперёд — контекст переключит эффект.
    const decision = evaluatePageGuard({
      pageType: target,
      role,
      kycStatus,
      activeStatus,
      statusEntries,
      bootstrapped,
    });
    if (decision.action === 'bounce') {
      if (decision.reason === 'admin') toast.error(t('guards.adminRequired'));
      else if (decision.reason === 'kyc') toast.info(t('guards.kycRequired'));
      else toast.info(t('guards.notAvailableHere'));
      navigateTo({ type: 'dashboard' });
      return;
    }
    navigateTo({ type: target } as Page);
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
      case 'product-edit': return [
        { label: getPageLabel('my-products', t), pageId: 'my-products' },
        { label: t('breadcrumbs.productEdit') },
      ];
      case 'deal-quote': return [
        { label: getPageLabel('crm-deals', t), pageId: 'crm-deals' },
        { label: t('pages.dealQuote.title') },
      ];
      default: return [{ label: getPageLabel(page.type, t) }];
    }
  };

  const { content, activePageId } = renderPage({
    page,
    role,
    activeStatus,
    navigateTo,
    onNavigate: handleNavigate,
    onProductClick: handleProductClick,
  });

  const breadcrumbs = getBreadcrumbs();
  const isPlatformAdmin = useUserStore((s) => s.role === 'ADMIN');
  // Workspace pages own the whole content viewport (no p-6 chrome, no page scroll, no
  // breadcrumb) so their internal layout can manage a single scroll — currently the КП builder.
  const fullBleed = page.type === 'deal-quote';

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
    <AppShell activePage={activePageId} onNavigate={handleNavigate} onStartTour={() => setShowTour(true)} fullBleed={fullBleed}>
      <Suspense fallback={<LoadingSkeleton />}>
        {!fullBleed && breadcrumbs.length > 0 && (
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
