import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { statusLabelKey, statusTone, type StatusCode, type StatusEntity, type StatusTone } from '@/lib/status';

/**
 * Тон → семантические токены темы кабинета (`packages/ui-tokens`, shadcnThemes.cabinet): текст статуса на его 10 %
 * заливке — пары «text-X на bg-X/10» поверх холста и рамки проверяет `contrast.test.mjs` (≥ 4.5:1, светлая и тёмная).
 */
const TONE_CLASS: Record<StatusTone, string> = {
  success: 'border-success/30 bg-success/10 text-success',
  warning: 'border-warning/30 bg-warning/10 text-warning',
  danger: 'border-destructive/30 bg-destructive/10 text-destructive',
  info: 'border-info/30 bg-info/10 text-info',
  neutral: 'border-border bg-muted text-muted-foreground',
};

export function ToneBadge({ tone, children, className }: { tone: StatusTone; children: React.ReactNode; className?: string }) {
  return (
    <Badge variant="outline" className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-normal', TONE_CLASS[tone], className)}>
      {children}
    </Badge>
  );
}

/** Бейдж статуса сущности контракта: подпись из `status.<entity>.<code>`, тон из `lib/status`. */
export function StatusBadge<E extends StatusEntity>({ entity, code }: { entity: E; code: StatusCode<E> }) {
  const { t } = useTranslation();
  return <ToneBadge tone={statusTone(entity, code)}>{t(statusLabelKey(entity, code))}</ToneBadge>;
}
