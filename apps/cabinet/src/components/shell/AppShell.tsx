import { useState, useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Copy, Eye, PanelLeft, PanelLeftClose, UserRound } from 'lucide-react';
import { toast } from '@/lib/toast';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useAppMode } from '@/session/mode';
import { useMe } from '@/session/useMe';
import { BottomNav } from './BottomNav';
import { SideNav } from './SideNav';
import { useTelegramBackButton } from './useTelegramBackButton';

const SIDEBAR_STORAGE_KEY = 'rt-cab-sidebar-collapsed-v1';

/**
 * Оболочка кабинета (Notion Floating Canvas):
 * - Внешний фон #F8F9FA (bg-alabaster).
 * - Слева сворачиваемый сайдбар SideNav (управление кнопкой и ⌘\ / Ctrl+\).
 * - Справа плавающий скругленный белый холст bg-canvas (rounded-2xl border border-silver/80).
 */
export function AppShell() {
  const { t } = useTranslation();
  const mode = useAppMode();
  const me = useMe().data;
  const location = useLocation();
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

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === '\\') {
        event.preventDefault();
        toggleSidebar();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Вычисление интерактивных хлебных крошек
  const getBreadcrumbs = (): Array<{ label: string; href?: string }> => {
    const path = location.pathname;
    const segments: Array<{ label: string; href?: string }> = [];

    if (path.startsWith('/requests/new')) {
      segments.push({ label: t('nav.requests'), href: '/requests' });
      segments.push({ label: t('pages.requests.new') });
    } else if (path.startsWith('/requests/')) {
      const id = path.replace('/requests/', '');
      segments.push({ label: t('nav.requests'), href: '/requests' });
      segments.push({ label: `№ ${id}` });
    } else if (path.startsWith('/requests')) {
      segments.push({ label: t('nav.requests') });
    } else if (path.startsWith('/quotes/')) {
      const id = path.replace('/quotes/', '');
      segments.push({ label: t('nav.quotes'), href: '/quotes' });
      segments.push({ label: `№ ${id}` });
    } else if (path.startsWith('/quotes')) {
      segments.push({ label: t('nav.quotes') });
    } else if (path.startsWith('/contracts')) {
      segments.push({ label: t('nav.contracts') });
    } else if (path.startsWith('/invoices')) {
      segments.push({ label: t('nav.invoices') });
    } else if (path.startsWith('/acts')) {
      segments.push({ label: t('nav.acts') });
    } else if (path.startsWith('/billing')) {
      segments.push({ label: t('nav.invoices') });
    } else if (path.startsWith('/deliveries')) {
      segments.push({ label: t('nav.deliveries') });
    } else if (path.startsWith('/documents')) {
      segments.push({ label: t('nav.documents') });
    } else if (path.startsWith('/catalog/')) {
      segments.push({ label: t('nav.catalog'), href: '/catalog' });
      segments.push({ label: t('pages.catalog.item', { defaultValue: 'Товар' }) });
    } else if (path.startsWith('/catalog')) {
      segments.push({ label: t('nav.catalog') });
    } else if (path.startsWith('/company')) {
      segments.push({ label: t('nav.company') });
    } else if (path.startsWith('/team')) {
      segments.push({ label: t('nav.company'), href: '/company' });
      segments.push({ label: t('nav.team') });
    } else if (path.startsWith('/deals/')) {
      const id = path.replace('/deals/', '');
      segments.push({ label: t('common.deal', { defaultValue: 'Сделка' }), href: '/requests' });
      segments.push({ label: `№ ${id}` });
    } else if (path.startsWith('/profile')) {
      segments.push({ label: t('nav.profile') });
    } else {
      segments.push({ label: t('app.name') });
    }
    return segments;
  };

  const breadcrumbs = getBreadcrumbs();

  return (
    <div className="min-h-dvh bg-alabaster text-charcoal md:flex">
      <a
        href="#main"
        className="sr-only z-50 rounded-xl bg-navy px-3 py-2 text-sm text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        {t('app.skipToContent')}
      </a>

      <SideNav
        companyName={me?.company.name}
        collapsed={sidebarCollapsed}
        onToggleCollapse={toggleSidebar}
      />

      <div className="flex min-w-0 flex-1 flex-col md:p-2.5">
        <div className="flex min-w-0 flex-1 flex-col rounded-none border-0 bg-canvas shadow-none md:rounded-2xl md:border md:border-silver/80 md:shadow-xs">
          {mode === 'web' ? (
            <header
              role="banner"
              className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-hairline bg-canvas/90 px-4 backdrop-blur md:rounded-t-2xl md:px-6"
            >
              {/* Левая часть: кнопка сворачивания + хлебные крошки */}
              <div className="flex min-w-0 items-center gap-2.5">
                <Button
                  variant="ghost"
                  size="icon"
                  className="hidden size-8 rounded-lg text-muted-foreground hover:bg-ice-navy hover:text-navy md:inline-flex"
                  onClick={toggleSidebar}
                  title={sidebarCollapsed ? t('nav.expandSidebar', { defaultValue: 'Развернуть меню (⌘\\)' }) : t('nav.collapseSidebar', { defaultValue: 'Свернуть меню (⌘\\)' })}
                  aria-label={sidebarCollapsed ? t('nav.expandSidebar', { defaultValue: 'Развернуть меню (⌘\\)' }) : t('nav.collapseSidebar', { defaultValue: 'Свернуть меню (⌘\\)' })}
                >
                  {sidebarCollapsed ? <PanelLeft className="size-4" /> : <PanelLeftClose className="size-4" />}
                </Button>

                <div className="min-w-0">
                  <nav aria-label={t('app.breadcrumbs', { defaultValue: 'Хлебные крошки' })} className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    <Link
                      to="/company"
                      className="truncate font-medium text-charcoal hover:text-navy hover:underline transition-colors"
                      title={me?.company.name || t('app.name')}
                    >
                      {me?.company.name || t('app.name')}
                    </Link>
                    {breadcrumbs.map((segment, index) => {
                      const isLast = index === breadcrumbs.length - 1;
                      return (
                        <span key={index} className="flex items-center gap-1.5 min-w-0">
                          <span className="text-muted-foreground/50">/</span>
                          {segment.href && !isLast ? (
                            <Link
                              to={segment.href}
                              className="truncate font-medium text-muted-foreground hover:text-navy hover:underline transition-colors"
                            >
                              {segment.label}
                            </Link>
                          ) : (
                            <span className={cn('truncate', isLast ? 'font-semibold text-navy' : 'font-medium text-charcoal')}>
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
                  className="rounded-xl p-2 text-muted-foreground outline-none transition-colors hover:bg-ice-navy hover:text-navy focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label={t('nav.profile')}
                  title={t('nav.profile')}
                >
                  <UserRound className="size-5" aria-hidden="true" />
                </Link>
              </div>
            </header>
          ) : null}

          <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 pt-4 pb-24 outline-none md:px-8 md:py-6">
            {me && !me.can_act ? (
              <div
                role="status"
                className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-hairline bg-ice-navy/60 p-3.5 text-sm text-navy"
              >
                <div className="flex items-center gap-2.5">
                  <Eye className="size-4 shrink-0 text-navy" aria-hidden="true" />
                  <span className="font-medium">{t('common.viewOnly')}</span>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl border-silver/80 bg-canvas text-xs text-navy hover:bg-ice-navy"
                  onClick={() => {
                    if (typeof navigator !== 'undefined' && navigator.clipboard) {
                      navigator.clipboard.writeText(window.location.href);
                      toast.success(t('common.linkCopied', { defaultValue: 'Ссылка скопирована' }));
                    }
                  }}
                >
                  <Copy className="size-3.5" aria-hidden="true" />
                  {t('common.copyLink', { defaultValue: 'Копировать ссылку' })}
                </Button>
              </div>
            ) : null}
            <Outlet />
          </main>
        </div>
      </div>

      <BottomNav />
    </div>
  );
}
