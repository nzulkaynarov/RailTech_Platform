import { useTranslation } from 'react-i18next';

import { initialsOf } from '@/lib/initials';
import { cn } from '@/lib/utils';

/**
 * Марка оператора в оболочке кабинета (CAB-FIX-2, K14): плитка основного цвета с буквами названия оператора — из
 * настроек компании (`{{operator}}`, задача «Н3a2»), не из кода. Имя для чтения экраном — у подписи рядом; без подписи
 * (свёрнутый сайдбар, шапка телефона) — `label`.
 */
export function BrandMark({ label, className }: { label?: string; className?: string }) {
  const { i18n } = useTranslation();
  const operator = String(i18n.options.interpolation?.defaultVariables?.operator ?? '');
  return (
    <span
      className={cn(
        'flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-xs font-bold tracking-tight text-primary-foreground shadow-xs',
        className,
      )}
      {...(label ? { role: 'img', 'aria-label': label, title: label } : { 'aria-hidden': true })}
    >
      {initialsOf(operator)}
    </span>
  );
}
