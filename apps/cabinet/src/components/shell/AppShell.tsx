import { useState, useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ChevronRight, Copy, Eye, PanelLeft, PanelLeftClose, UserRound } from 'lucide-react';
import { toast } from '@/lib/toast';

import { TelegramBanner } from '@/components/TelegramBanner';
import { Button } from '@/components/ui/button';
import { usePageTitle } from '@/hooks/usePageTitle';
import { isSidebarToggle, shortcutLabel } from '@/lib/keyboard';
import { copyText, shareableUrl } from '@/lib/shareLink';
import { cn } from '@/lib/utils';
import { useAppMode } from '@/session/mode';
import { useCanAct, useMe } from '@/session/useMe';
import { useNav } from '@/session/useNav';
import { BottomNav } from './BottomNav';
import { BrandMark } from './BrandMark';
import { SetCrumbContext, type PageCrumb } from './crumbs';
import { SideNav } from './SideNav';
import { useTelegramBackButton } from './useTelegramBackButton';

const SIDEBAR_STORAGE_KEY = 'rt-cab-sidebar-collapsed-v1';

/**
 * Оболочка кабинета (Floating Canvas):
 * - Внешний фон — рамка bg-muted (в Mini App — secondary_bg_color Telegram).
 * - Слева сворачиваемый сайдбар SideNav (управление кнопкой и ⌘\ / Ctrl+\).
 * - Справа плавающий скругленный холст bg-background (rounded-2xl border border-border; в Mini App — bg_color Telegram).
 */
export function AppShell() {
  const { t } = useTranslation();
  const mode = useAppMode();
  const me = useMe().data;
  const canAct = useCanAct();
  const nav = useNav();
  const location = useLocation();
  const [pageCrumb, setPageCrumb] = useState<PageCrumb | null>(null);
  useTelegramBackButton();

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true';
    } catch {
      return false;
    }
  });

  const toggleSidebar = () => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
      } catch {
        // ignore
      }
      return next;
    });
  };

  // ⌘\ / Ctrl+\ — по физической клавише (работает и в RU-раскладке), не в полях ввода (K12)
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!isSidebarToggle(event)) return;
      event.preventDefault();
      toggleSidebar();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Хлебные крошки: разделы — ссылки, документ — его номер из данных экрана (usePageCrumb), без внутреннего id (K14)
  const crumb = pageCrumb?.path === location.pathname ? pageCrumb.label : null;
  const getBreadcrumbs = (): Array<{ label: string; href?: string }> => {
    const path = location.pathname;
    const segments: Array<{ label: string; href?: string }> = [];

    if (path.startsWith('/requests/new')) {
      segments.push({ label: t('nav.requests'), href: '/requests' });
      segments.push({ label: t('pages.requests.new') });
    } else if (path.startsWith('/requests/')) {
      segments.push({ label: t('nav.requests'), href: '/requests' });
      segments.push({ label: crumb ?? t('crumbs.request') });
    } else if (path.startsWith('/requests')) {
      segments.push({ label: t('nav.requests') });
    } else if (path.startsWith('/quotes/')) {
      segments.push({ label: t('nav.quotes'), href: '/quotes' });
      segments.push({ label: crumb ?? t('crumbs.quote') });
    } else if (path.startsWith('/quotes')) {
      segments.push({ label: t('nav.quotes') });
    } else if (path.startsWith('/contracts')) {
      segments.push({ label: t('nav.contracts') });
    } else if (path.startsWith('/invoices')) {
      segments.push({ label: t('nav.invoices') });
    } else if (path.startsWith('/acts')) {
      segments.push({ label: t('nav.acts') });
    } else if (path.startsWith('/deliveries')) {
      segments.push({ label: t('nav.deliveries') });
    } else if (path.startsWith('/documents')) {
      segments.push({ label: t('nav.documents') });
    } else if (path.startsWith('/catalog/')) {
      segments.push({ label: t('nav.catalog'), href: '/catalog' });
      segments.push({ label: crumb ?? t('crumbs.catalogItem') });
    } else if (path.startsWith('/catalog')) {
      segments.push({ label: t('nav.catalog') });
    } else if (path.startsWith('/company')) {
      segments.push({ label: t('nav.company') });
    } else if (path.startsWith('/team')) {
      segments.push({ label: t('nav.company'), href: '/company' });
      segments.push({ label: t('nav.team') });
    } else if (path.startsWith('/deals/')) {
      // Списка сделок у клиента нет — «Сделка» текстом, не ссылкой на чужой раздел
      segments.push({ label: t('crumbs.deal') });
      if (crumb) segments.push({ label: crumb });
    } else if (path.startsWith('/profile')) {
      segments.push({ label: t('nav.profile') });
    } else {
      segments.push({ label: t('app.name') });
    }
    return segments;
  };

  const breadcrumbs = getBreadcrumbs();

  // Ссылка для коллеги с правом действовать: адрес страницы без #… и служебных параметров (K15); в Mini App кнопки нет
  const copyPageLink = async () => {
    if (await copyText(shareableUrl(window.location))) toast.success(t('common.linkCopied'));
    else toast.error(t('common.copyLinkFailed'));
  };

  return (
    <SetCrumbContext.Provider value={setPageCrumb}>
      <div className="min-h-dvh bg-muted text-foreground md:flex">
        <a
          href="#main"
          className="sr-only z-50 rounded-xl bg-primary px-3 py-2 text-sm text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        >
          {t('app.skipToContent')}
        </a>

        <SideNav companyName={me?.company.name} collapsed={sidebarCollapsed} onToggleCollapse={toggleSidebar} />

        <div className="flex min-w-0 flex-1 flex-col md:p-2.5">
          <div className="flex min-w-0 flex-1 flex-col rounded-none border-0 bg-background shadow-none md:rounded-2xl md:border md:border-border md:shadow-xs">
            {mode === 'web' ? (
              <header
                role="banner"
                className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-border/60 bg-background/90 px-4 backdrop-blur md:rounded-t-2xl md:px-6"
              >
                {/* Левая часть: кнопка сворачивания + хлебные крошки */}
                <div className="flex min-w-0 items-center gap-2.5">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="hidden size-8 rounded-lg text-muted-foreground hover:bg-accent hover:text-primary md:inline-flex"
                    onClick={toggleSidebar}
                    title={`${sidebarCollapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')} (${shortcutLabel('\\')})`}
                    aria-label={sidebarCollapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
                  >
                    {sidebarCollapsed ? (
                      <PanelLeft className="size-4" aria-hidden="true" />
                    ) : (
                      <PanelLeftClose className="size-4" aria-hidden="true" />
                    )}
                  </Button>

                  {/* Телефон: сайдбара нет — марка RailTech в шапке */}
                  <Link
                    to="/"
                    title={t('app.name')}
                    className="shrink-0 rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring md:hidden"
                  >
                    <BrandMark className="size-8" />
                    <span className="sr-only">{t('app.name')}</span>
                  </Link>

                  <div className="min-w-0">
                    <nav
                      aria-label={t('app.breadcrumbs')}
                      className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground"
                    >
                      <Link
                        to="/company"
                        className="truncate font-medium text-foreground hover:text-primary hover:underline transition-colors"
                        title={me?.company.name || t('app.name')}
                      >
                        {me?.company.name || t('app.name')}
                      </Link>
                      {breadcrumbs.map((segment, index) => {
                        const isLast = index === breadcrumbs.length - 1;
                        return (
                          <span key={index} className="flex items-center gap-1.5 min-w-0">
                            <ChevronRight className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
                            {segment.href && !isLast ? (
                              <Link
                                to={segment.href}
                                className="truncate font-medium text-muted-foreground hover:text-primary hover:underline transition-colors"
                              >
                                {segment.label}
                              </Link>
                            ) : (
                              <span
                                className={cn(
                                  'truncate',
                                  isLast ? 'font-semibold text-primary' : 'font-medium text-foreground',
                                )}
                              >
                                {segment.label}
                              </span>
                            )}
                          </span>
                        );
                      })}
                    </nav>
                  </div>
                </div>

                {/* Правая часть: ссылка на профиль */}
                <div className="flex items-center gap-2">
                  <Link
                    to="/profile"
                    className="rounded-xl p-2 text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={t('nav.profile')}
                    title={t('nav.profile')}
                  >
                    <UserRound className="size-5" aria-hidden="true" />
                  </Link>
                </div>
              </header>
            ) : null}

            <main
              id="main"
              tabIndex={-1}
              className="mx-auto w-full max-w-6xl flex-1 px-4 pt-4 pb-24 outline-none md:px-8 md:py-6"
            >
              {me && !canAct ? (
                <div
                  role="status"
                  className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border/60 bg-accent/60 p-3.5 text-sm text-primary"
                >
                  <div className="flex items-center gap-2.5">
                    <Eye className="size-4 shrink-0 text-primary" aria-hidden="true" />
                    <span className="font-medium">{t('common.viewOnly')}</span>
                  </div>
                  {mode === 'web' ? (
                    <Button
                      variant="outline"
                      size="sm"
                      className="rounded-xl border-border bg-background text-xs text-primary hover:bg-accent"
                      onClick={() => void copyPageLink()}
                    >
                      <Copy className="size-3.5" aria-hidden="true" />
                      {t('common.copyLink')}
                    </Button>
                  ) : null}
                </div>
              ) : null}
              {nav.work.length === 0 && location.pathname !== '/profile' ? <NoSections /> : <Outlet />}
            </main>
          </div>
        </div>

        {me ? <TelegramBanner onProfile={location.pathname === '/profile'} /> : null}
        <BottomNav />
      </div>
    </SetCrumbContext.Provider>
  );
}

/**
 * Сессия без известных Cabinet разделов (`/me.modules` пуст или модули пока не имеют экранов, ADR-0022): доступ открыт,
 * разделы настраивает менеджер. Один простой экран вместо меню и заглушек «скоро».
 */
function NoSections() {
  const { t } = useTranslation();
  usePageTitle(t('access.noSections.title'));
  return (
    <section className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center" aria-live="polite">
      <h1 className="text-xl font-semibold">{t('access.noSections.title')}</h1>
      <p className="text-sm text-muted-foreground">{t('access.noSections.text')}</p>
    </section>
  );
}
