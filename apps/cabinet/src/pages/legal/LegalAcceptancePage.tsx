import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useAppName } from '@/i18n/operator';
import { Check } from 'lucide-react';

import { apiErrorKey } from '@/api/errors';
import type { LegalLang } from '@/api/portal';
import { useAcceptLegal, useLegal } from '@/api/queries';
import { LegalDocument } from '@/components/legal/LegalDocument';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { BrandMark } from '@/components/shell/BrandMark';
import { StatusScreen } from '@/components/StatusScreen';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { usePageTitle } from '@/hooks/usePageTitle';
import { localeFor } from '@/i18n/locales';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/utils';
import { rememberLegalDecline } from '@/session/legalDecline';
import { useAppMode } from '@/session/mode';
import { useLogout } from '@/session/useMe';

type Kind = 'privacy' | 'terms';
const ORDER: Kind[] = ['terms', 'privacy'];

/**
 * Принятие оферты и политики (ДВ-5): вместо кабинета, пока у контакта есть действующая редакция без его акцепта — при
 * первом входе и при каждой новой редакции. Оба документа читаются на языке интерфейса (переключатель рядом), одно явное
 * действие «Принимаю» записывает редакцию, дату и язык на сервере. Отказ — выход из кабинета с объяснением (в Mini App
 * сессию Telegram не закрыть: сервер и так держит кабинет закрытым, показывается объяснение).
 */
export function LegalAcceptancePage() {
  const { t, i18n } = useTranslation();
  const appName = useAppName();
  const lang = localeFor(i18n.resolvedLanguage ?? i18n.language).code as LegalLang;
  const mode = useAppMode();
  const legal = useLegal();
  const accept = useAcceptLegal();
  const logout = useLogout();
  const [kind, setKind] = useState<Kind>('terms');
  const [declined, setDeclined] = useState(false);
  usePageTitle(t('legal.title'));

  if (declined) {
    return (
      <StatusScreen title={t('legal.declined.title')} text={t('legal.declined.text')}>
        <Button onClick={() => setDeclined(false)}>{t('legal.declined.back')}</Button>
      </StatusScreen>
    );
  }
  if (legal.isPending) return <StatusScreen title={t('app.loading')} loading />;
  if (legal.isError || !legal.data) {
    return (
      <StatusScreen title={t('common.error')} text={t(apiErrorKey(legal.error))}>
        <Button onClick={() => void legal.refetch()}>{t('common.retry')}</Button>
      </StatusScreen>
    );
  }

  const editions = ORDER.map((k) => legal.data.editions.find((edition) => edition.kind === k)).filter(
    (edition): edition is NonNullable<typeof edition> => Boolean(edition),
  );
  const shown = editions.find((edition) => edition.kind === kind) ?? editions[0];
  const onAccept = () => accept.mutate({ editionIds: editions.map((edition) => edition.id), language: lang });
  const onDecline = () => {
    if (mode === 'miniapp') {
      setDeclined(true);
      return;
    }
    rememberLegalDecline();
    logout.mutate();
  };

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
          <div className="flex flex-col gap-1">
            <h1 className="text-xl font-semibold">{t('legal.title')}</h1>
            <p className="text-sm text-muted-foreground">{t('legal.intro')}</p>
          </div>
          {shown ? (
            <div className="flex flex-col gap-2 rounded-lg border bg-card">
              <div role="tablist" aria-label={t('legal.documents')} className="flex flex-wrap gap-1 border-b p-2">
                {editions.map((edition) => {
                  const active = edition.kind === shown.kind;
                  return (
                    <Button
                      key={edition.kind}
                      role="tab"
                      id={`legal-tab-${edition.kind}`}
                      aria-selected={active}
                      aria-controls="legal-panel"
                      type="button"
                      size="sm"
                      variant="outline"
                      className={cn(active && 'border-primary bg-primary/5 text-primary hover:bg-primary/10 hover:text-primary')}
                      onClick={() => setKind(edition.kind)}
                    >
                      {t(`legal.tabs.${edition.kind}`)}
                    </Button>
                  );
                })}
              </div>
              <div
                id="legal-panel"
                role="tabpanel"
                aria-labelledby={`legal-tab-${shown.kind}`}
                tabIndex={0}
                className="max-h-[55dvh] overflow-y-auto px-4 pb-4 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <p className="pb-3 text-xs text-muted-foreground">{t('legal.edition', { date: formatDate(shown.published_at, lang) })}</p>
                <LegalDocument edition={shown} lang={lang} />
              </div>
            </div>
          ) : null}
          {accept.isError ? (
            <Alert variant="destructive">
              <AlertDescription>{t(apiErrorKey(accept.error))}</AlertDescription>
            </Alert>
          ) : null}
          <p className="rounded-md bg-background px-3 py-2 text-xs text-muted-foreground">{t('legal.consent')}</p>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" disabled={accept.isPending || logout.isPending} onClick={onDecline}>
              {t('legal.decline')}
            </Button>
            <Button type="button" disabled={accept.isPending || editions.length === 0} onClick={onAccept}>
              <Check aria-hidden="true" />
              {accept.isPending ? t('legal.accepting') : t('legal.accept')}
            </Button>
          </div>
        </div>
      </main>
    </div>
  );
}
