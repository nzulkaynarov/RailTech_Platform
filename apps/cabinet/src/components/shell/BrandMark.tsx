import { useState } from 'react';
import { LayoutGrid } from 'lucide-react';

import { useOperator } from '@/i18n/operator';

import { initialsOf } from '@/lib/initials';
import { cn } from '@/lib/utils';

/**
 * Марка оператора в оболочке кабинета (CAB-FIX-2, K14): логотип своей компании оператора (ДВ-3, `GET /operator`
 * → `logo_url`), а без него или если файл не открылся — плитка основного цвета с буквами названия оператора из настроек
 * компании (`{{operator}}`, задача «Н3a2»), не из кода. Имя для чтения экраном — у подписи рядом; без подписи
 * (свёрнутый сайдбар, шапка телефона) — `label`.
 */
export function BrandMark({ label, className }: { label?: string; className?: string }) {
  const operatorData = useOperator().data;
  const logo = operatorData?.logo_url;
  // Название не задано (или ещё не пришло) — нейтральный значок, а не буквы слова-заглушки («ПЛ» от «платформа»).
  const operatorName = operatorData?.name?.trim() ?? '';
  const named = operatorName !== '';
  const [broken, setBroken] = useState<string | null>(null);
  const a11y = label ? { alt: label, title: label } : { alt: '', 'aria-hidden': true as const };
  if (logo && broken !== logo) {
    return (
      <img
        src={logo}
        {...a11y}
        onError={() => setBroken(logo)}
        className={cn('size-9 shrink-0 rounded-lg bg-white object-contain p-0.5 shadow-xs', className)}
      />
    );
  }
  return (
    <span
      className={cn(
        'flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-xs font-bold tracking-tight text-primary-foreground shadow-xs',
        className,
      )}
      {...(label ? { role: 'img', 'aria-label': label, title: label } : { 'aria-hidden': true })}
    >
      {named ? initialsOf(operatorName) : <LayoutGrid className="size-4" aria-hidden="true" />}
    </span>
  );
}
