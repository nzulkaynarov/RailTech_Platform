import { Link, Outlet } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Eye, UserRound } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { useAppMode } from '@/session/mode';
import { useMe } from '@/session/useMe';
import { BottomNav } from './BottomNav';
import { SideNav } from './SideNav';
import { useTelegramBackButton } from './useTelegramBackButton';

/**
 * Оболочка кабинета (своя, не AppShell ERP — CONVENTIONS.md §4): телефон — шапка и нижняя навигация,
 * десктоп — боковая навигация. В Mini App шапки нет: заголовок и «Назад» даёт Telegram.
 */
export function AppShell() {
  const { t } = useTranslation();
  const mode = useAppMode();
  const me = useMe().data;
  useTelegramBackButton();

  return (
    <div className="min-h-dvh bg-background text-foreground md:flex">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        {t('app.skipToContent')}
      </a>
      <SideNav companyName={me?.company.name} />
      <div className="flex min-w-0 flex-1 flex-col">
        {mode === 'web' ? (
          <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b bg-background px-4 py-2 md:hidden">
            <div className="min-w-0">
              <p className="text-sm font-semibold">{t('app.name')}</p>
              {me ? <p className="truncate text-xs text-muted-foreground">{me.company.name}</p> : null}
            </div>
            <Link
              to="/profile"
              className="rounded-md p-2 text-muted-foreground outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
              aria-label={t('nav.profile')}
              title={t('nav.profile')}
            >
              <UserRound className="size-5" aria-hidden="true" />
            </Link>
          </header>
        ) : null}
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 pt-4 pb-24 outline-none md:px-8 md:py-6">
          {me && !me.can_act ? (
            <Alert role="status" className="mb-4">
              <Eye aria-hidden="true" />
              <AlertDescription>{t('common.viewOnly')}</AlertDescription>
            </Alert>
          ) : null}
          <Outlet />
        </main>
      </div>
      <BottomNav />
    </div>
  );
}
