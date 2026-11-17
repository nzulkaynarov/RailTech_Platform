import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { BrandMark } from '@/components/shell/BrandMark';
import { usePageTitle } from '@/hooks/usePageTitle';

/**
 * Каркас публичных экранов веба (вход, «письмо отправлено», «Я новый клиент»): марка и название оператора, язык,
 * карточка и строка против фишинга (ДВ-3: мы не просим пароль и код).
 */
export function AuthLayout({ title, children }: { title: string; children: ReactNode }) {
  const { t } = useTranslation();
  usePageTitle(title);
  return (
    <div className="flex min-h-dvh flex-col bg-muted text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <div className="flex items-center gap-3">
          <BrandMark />
          <div>
            <p className="text-sm font-semibold">{t('app.name')}</p>
            <p className="text-xs text-muted-foreground">{t('app.tagline')}</p>
          </div>
        </div>
        <LanguageSwitcher />
      </header>
      <main id="main" className="flex flex-1 items-start justify-center px-4 pt-4 pb-10 md:items-center">
        <div className="flex w-full max-w-md flex-col gap-4">
          {children}
          <p className="rounded-md bg-background px-3 py-2 text-xs text-muted-foreground">{t('auth.antiPhishing')}</p>
        </div>
      </main>
    </div>
  );
}
