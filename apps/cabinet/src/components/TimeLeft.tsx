import { useTranslation } from 'react-i18next';

import { businessToday, daysBetween } from '@/lib/format';
import { cn } from '@/lib/utils';

/**
 * «Осталось N дней» рядом со сроком (план §3f РЕФ-3): срок читается без подсчёта. Показывается только у открытого срока
 * в будущем или сегодня; просрочку показывает статус объекта. Два дня и меньше — цветом предупреждения.
 */
export function TimeLeft({ date, now, className }: { date?: string | null; now: number; className?: string }) {
  const { t } = useTranslation();
  if (!date) return null;
  const days = daysBetween(businessToday(now), date.slice(0, 10));
  if (Number.isNaN(days) || days < 0) return null;
  return (
    <span className={cn('whitespace-nowrap text-xs', days <= 2 ? 'font-medium text-warning' : 'text-muted-foreground', className)}>
      {days === 0 ? t('common.timeLeft.today') : t('common.timeLeft.days', { count: days })}
    </span>
  );
}
