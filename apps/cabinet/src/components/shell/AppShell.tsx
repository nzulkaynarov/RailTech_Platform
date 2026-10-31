import { useState, useEffect } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Copy, Eye, PanelLeft, PanelLeftClose, UserRound } from 'lucide-react';
import { toast } from '@/lib/toast';

import { Button } from '@/components/ui/button';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
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

  // Вычисление хлебных крошек
  const getBreadcrumbs = () => {
    const path = location.pathname;
    if (path.startsWith('/requests')) return t('nav.requests');
    if (path.startsWith('/quotes')) return t('nav.quotes');
    if (path.startsWith('/contracts')) return t('nav.contracts');
    if (path.startsWith('/invoices')) return t('nav.invoices');
    if (path.startsWith('/acts')) return t('nav.acts');
    if (path.startsWith('/deliveries')) return t('nav.deliveries');
    if (path.startsWith('/documents')) return t('nav.documents');
    if (path.startsWith('/catalog')) return t('nav.catalog');
    if (path.startsWith('/company')) return t('nav.company');
    if (path.startsWith('/team')) return t('nav.team');
    if (path.startsWith('/deals')) return t('common.deal', { defaultValue: 'Сделка' });
    if (path.startsWith('/profile')) return t('nav.profile');
    return t('app.name');
  };

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
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span className="truncate font-medium text-charcoal md:inline">{me?.company.name || t('app.name')}</span>
                    <span className="text-muted-foreground/60">/</span>
                    <span className="truncate font-semibold text-navy">{getBreadcrumbs()}</span>
                  </div>
                </div>
              </div>

              {/* Правая часть: переключатель языка и ссылка на профиль */}
              <div className="flex items-center gap-2">
                <div className="hidden sm:inline-flex">
                  <LanguageSwitcher />
                </div>
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
