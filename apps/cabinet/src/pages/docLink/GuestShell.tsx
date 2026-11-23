import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { BrandMark } from '@/components/shell/BrandMark';
import { usePageTitle } from '@/hooks/usePageTitle';

/**
 * Каркас гостя по ссылке документа (ДК-1): марка, подпись «вы смотрите один документ», язык — и ничего от кабинета:
 * меню, разделов и сведений о компании гость не видит и не узнаёт, что они есть.
 */
export function GuestShell({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  const { t } = useTranslation();
  usePageTitle(title);
  return (
    <div className="flex min-h-dvh flex-col bg-muted text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b bg-background px-4 py-3">
        <div className="flex items-center gap-3">
          <BrandMark />
          <p className="text-sm font-semibold">{t('app.name')}</p>
        </div>
        {note ? <p className="order-last w-full text-sm text-muted-foreground break-words sm:order-none sm:w-auto">{note}</p> : null}
        <LanguageSwitcher />
      </header>
      <main id="main" className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-4 py-6">
        {children}
      </main>
    </div>
  );
}
