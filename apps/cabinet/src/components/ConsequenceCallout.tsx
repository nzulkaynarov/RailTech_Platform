import { useTranslation } from 'react-i18next';
import { Info } from 'lucide-react';

import { cn } from '@/lib/utils';

/**
 * «Что произойдёт» рядом с главной кнопкой необратимого действия: текст передаёт экран, и он описывает только то,
 * что действительно делают ERP и CRM после действия, — без сроков и обещаний, которых нет в процессе (CAB-FIX-1).
 * Блок без действия рядом не ставится.
 */
export function ConsequenceCallout({ text, className }: { text: string; className?: string }) {
  const { t } = useTranslation();
  return (
    <div
      role="note"
      className={cn('flex items-start gap-3 rounded-xl border border-hairline bg-ice-navy/80 p-3.5 text-xs text-navy', className)}
    >
      <div className="flex size-5 shrink-0 items-center justify-center rounded-full bg-navy text-primary-foreground">
        <Info className="size-3 text-primary-foreground" aria-hidden="true" />
      </div>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="font-semibold tracking-tight text-navy">{t('common.whatHappens')}</span>
        <p className="leading-relaxed text-charcoal">{text}</p>
      </div>
    </div>
  );
}
