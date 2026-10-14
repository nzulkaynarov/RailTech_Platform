import { Suspense, useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AppShell } from './layouts/AppShell';
import { ErrorBoundary } from './components/Shared/ErrorBoundary';
import { OnboardingTour } from './components/Shared/OnboardingTour';
import { PageBreadcrumb } from './components/Shared/PageBreadcrumb';
import { getPageLabel } from '@/lib/pageLabels';
import { useUserStore } from './store/userStore';
import { useAuthStore } from './store/authStore';
import { LoginPage } from './components/Auth/LoginPage';
import { PasswordSetupPage } from './components/Auth/PasswordSetupPage';
import { ForgotPasswordPage } from './components/Auth/ForgotPasswordPage';
import { ResetPasswordPage } from './components/Auth/ResetPasswordPage';
import { NoCompanyScreen } from './components/Auth/NoCompanyScreen';
import { LoadingSkeleton } from './components/LoadingSkeleton';
import { NAVIGABLE_PAGES } from './config/pageRegistry';
import { parseHashToPage, pageToHash, type Page } from './routes/hashRoute';
import { evaluatePageGuard } from './routes/pageGuard';
import { renderPage } from './routes/pageContent';

/** Parse URL path and query params for auth routes */
type AuthRouteView = 'login' | 'setup-password' | 'forgot-password' | 'reset-password';

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
  return { view: 'login', uid: null, token: null };
}

function useAuthRoute() {
  const [route, setRoute] = useState(parseAuthRoute);

  const navigate = (view: Extract<AuthRouteView, 'login' | 'forgot-password'>) => {
    const pathMap: Record<typeof view, string> = {
      login: '/',
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

  // Not authenticated — login only: self-registration is gone (M1-ERP-02). Employees are
  // provisioned by CRM (ADR-0003) or invited by a teammate (setup-password link above).
  if (!isAuthenticated) {
    return (
      <LoginPage
        onNavigate={() => {}}
        onForgotPassword={() => navigate('forgot-password')}
      />
    );
  }

  // Authenticated but not attached to a company. There is no self-service company creation
  // any more — the back office or CRM attaches the account; say so instead of a dead form.
  const hasCompany = user?.company || user?.primary_company;
  if (!hasCompany) {
    return <NoCompanyScreen />;
  }

  return (
    <ErrorBoundary>
      <MainApp />
    </ErrorBoundary>
  );
}

function MainApp() {
  const { t } = useTranslation();
  const [page, setPage] = useState<Page>(() => parseHashToPage(window.location.hash));
  const [showTour, setShowTour] = useState(false);

  const navigateTo = (p: Page) => {
    setPage(p);
    // Sync URL hash with current page for browser back/forward
    window.history.pushState({ page: p }, '', `#${pageToHash(p)}`);
  };

  // Гейт страницы (`evaluatePageGuard`): контекста «покупатель / продавец» больше нет
  // (M1-ERP-02 волна 3), поэтому гейт отбрасывает только устаревший/неизвестный хэш
  // (старая закладка `#my-requests`, `#admin-*`) — с объяснением и на дашборд.
  useEffect(() => {
    if (evaluatePageGuard(page.type).action === 'allow') return;
    toast.info(t('guards.notAvailableHere'));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- гейт страницы: не синхронизация, а НАВИГАЦИЯ с побочными действиями (toast + history.replaceState)
    setPage({ type: 'dashboard' });
    window.history.replaceState(null, '', '#dashboard');
  }, [page.type, t]);

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
    // deep-links: approval queue, notifications, catalog bulk-import). Those fire
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
    // ЛЮБАЯ параметрная цель («product-edit/42», «request-detail/21», «acts?open=4») разбирается
    // тем же парсером, что и адресная строка. Раньше здесь был частный случай ровно на один
    // маршрут (`product-edit/`), а остальные проваливались в проверку `NAVIGABLE_PAGES`, где
    // хранятся ГОЛЫЕ идентификаторы, — и молча уводили на дашборд. Так терялись переходы из
    // шторки сообщений и, что дороже, ИЗ УВЕДОМЛЕНИЙ: ссылка «КП согласовано» вела не к сделке,
    // а на главную (найдено прогоном глазами 19-08). Гейт считается по ТИПУ страницы, как и был.
    if (target.includes('/') || target.includes('?')) {
      const parsed = parseHashToPage(target);
      if (evaluatePageGuard(parsed.type).action === 'bounce') {
        toast.info(t('guards.notAvailableHere'));
        navigateTo({ type: 'dashboard' });
        return;
      }
      // Параметры (`?open=4`) страница читает сама — сохраняем их в адресе как есть.
      setPage(parsed);
      window.history.pushState({ page: parsed }, '', `#${target}`);
      return;
    }
    // Цели меню — из реестра страниц (`navigable`). Раньше здесь лежал четвёртый
    // рукописный список идентификаторов, и он уже расходился с остальными: пункт
    // «Клиенты» существовал и в рендере, и в наборах контекста, но отсутствовал ЗДЕСЬ —
    // клик по нему молча уводил на дашборд (ADR-0005 Phase F).
    if (!NAVIGABLE_PAGES.has(target)) {
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
        { label: getPageLabel('my-products', t), pageId: 'my-products' },
        { label: t('breadcrumb.productDetail') },
      ];
      case 'request-detail': return [
        { label: getPageLabel('crm-deals', t), pageId: 'crm-deals' },
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
    navigateTo,
    onNavigate: handleNavigate,
    onProductClick: handleProductClick,
  });

  const breadcrumbs = getBreadcrumbs();
  // Workspace pages own the whole content viewport (no p-6 chrome, no page scroll, no
  // breadcrumb) so their internal layout can manage a single scroll — currently the КП builder.
  const fullBleed = page.type === 'deal-quote';

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
