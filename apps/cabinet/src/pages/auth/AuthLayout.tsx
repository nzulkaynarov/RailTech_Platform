import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { usePageTitle } from '@/hooks/usePageTitle';

/** Каркас публичных экранов веба (вход, «письмо отправлено», «Я новый клиент»): бренд, язык, карточка. */
export function AuthLayout({ title, children }: { title: string; children: ReactNode }) {
  const { t } = useTranslation();
  usePageTitle(title);
  return (
    <div className="flex min-h-dvh flex-col bg-muted text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <div>
          <p className="text-sm font-semibold">{t('app.name')}</p>
          <p className="text-xs text-muted-foreground">{t('app.tagline')}</p>
        </div>
        <LanguageSwitcher />
      </header>
      <main id="main" className="flex flex-1 items-start justify-center px-4 pt-4 pb-10 md:items-center">
        <div className="flex w-full max-w-md flex-col gap-4">{children}</div>
      </main>
    </div>
  );
}
