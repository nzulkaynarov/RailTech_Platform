import { useTranslation } from 'react-i18next';

import { useAppName } from '@/i18n/operator';
import { Link } from 'react-router-dom';

import type { LegalLang } from '@/api/portal';
import { useLegalPolicy } from '@/api/queries';
import { LegalDocument } from '@/components/legal/LegalDocument';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { BrandMark } from '@/components/shell/BrandMark';
import { Button } from '@/components/ui/button';
import { usePageTitle } from '@/hooks/usePageTitle';
import { localeFor } from '@/i18n/locales';
import { formatDate } from '@/lib/format';

/** Политика обработки персональных данных до входа (ДВ-5): ссылка с экрана входа. Показывает действующую редакцию. */
export function PrivacyPage() {
  const { t, i18n } = useTranslation();
  const appName = useAppName();
  const lang = localeFor(i18n.resolvedLanguage ?? i18n.language).code as LegalLang;
  const query = useLegalPolicy();
  const policy = query.data?.policy ?? null;
  usePageTitle(t('legal.policyLink'));
  return (
    <div className="flex min-h-dvh flex-col bg-muted text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <div className="flex items-center gap-3">
          <BrandMark />
          <p className="text-sm font-semibold">{appName}</p>
        </div>
        <LanguageSwitcher />
      </header>
      <main id="main" className="flex flex-1 justify-center px-4 pt-2 pb-8">
        <div className="flex w-full max-w-3xl flex-col gap-4">
          {policy ? (
            <div className="rounded-lg border bg-card p-4">
              <p className="pb-3 text-xs text-muted-foreground">{t('legal.edition', { date: formatDate(policy.published_at, lang) })}</p>
              <LegalDocument edition={policy} lang={lang} headingLevel={1} />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{query.isPending ? t('app.loading') : t('legal.notPublished')}</p>
          )}
          <Button asChild variant="outline" className="self-start">
            <Link to="/login">{t('legal.backToLogin')}</Link>
          </Button>
        </div>
      </main>
    </div>
  );
}
