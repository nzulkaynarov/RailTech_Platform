import React from 'react';
import { useTranslation } from 'react-i18next';
import { Globe } from 'lucide-react';
import { clsx } from 'clsx';

import { LOCALES, localeFor } from '@/i18n/locales';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

/**
 * Переключатель языка — СПИСОК из реестра локалей, а не тумблер на два значения (L3).
 *
 * Прежний тумблер `isRu ? 'en' : 'ru'` делал третий язык невыразимым; со списком узбекский
 * (в двух скриптах) появится добавлением строки в `locales.ts`. Подписи — на своём языке:
 * человек, не читающий текущий язык интерфейса, обязан найти свой.
 */
export const LanguageSwitcher: React.FC<{ className?: string }> = ({ className }) => {
  const { i18n, t } = useTranslation();
  const active = localeFor(i18n.language);

  // Один язык — переключать нечего, кнопка была бы ложным обещанием выбора.
  if (LOCALES.length < 2) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          aria-label={t('languageSwitcher.choose')}
          className={clsx('flex items-center gap-1.5 h-auto', className)}
        >
          <Globe size={14} />
          <span>{active.shortLabel}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {LOCALES.map((locale) => (
          <DropdownMenuItem
            key={locale.code}
            onClick={() => i18n.changeLanguage(locale.code)}
            className={clsx(locale.code === active.code && 'font-semibold')}
          >
            {locale.nativeName}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
