import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { chooseLanguage } from '@/i18n';
import { LOCALES, localeFor } from '@/i18n/locales';
import { cn } from '@/lib/utils';

/**
 * Переключатель ru / uz / en: три кнопки вместо выпадающего списка — на телефоне один тап,
 * подписи на своём языке (`lang`), видимый текст = доступное имя (WCAG 2.5.3), выбор запоминается.
 */
export function LanguageSwitcher({ className }: { className?: string }) {
  const { t, i18n } = useTranslation();
  const current = localeFor(i18n.resolvedLanguage ?? i18n.language).code;

  return (
    <div role="group" aria-label={t('languages.label')} className={cn('inline-flex flex-wrap gap-1', className)}>
      {LOCALES.map((locale) => {
        const active = locale.code === current;
        return (
          <Button
            key={locale.code}
            type="button"
            size="sm"
            variant={active ? 'default' : 'outline'}
            aria-pressed={active}
            lang={locale.code}
            onClick={() => void chooseLanguage(locale.code)}
          >
            {locale.nativeName}
          </Button>
        );
      })}
    </div>
  );
}
