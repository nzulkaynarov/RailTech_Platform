import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { statusLabelKey, statusTone, type StatusEntity, type StatusTone } from '@/lib/status';
import type { Schemas } from '@/api/portal';

/** Тон → семантические токены (как `StatusBadge` B2B/ERP): цвет несёт смысл, подпись — всегда текстом. */
const TONE_CLASS: Record<StatusTone, string> = {
  success: 'border-success/30 bg-success/10 text-success',
  warning: 'border-warning/30 bg-warning/10 text-warning',
  danger: 'border-destructive/30 bg-destructive/10 text-destructive',
  info: 'border-info/30 bg-info/10 text-info',
  neutral: 'border-border bg-muted text-muted-foreground',
};

export function ToneBadge({ tone, children, className }: { tone: StatusTone; children: React.ReactNode; className?: string }) {
  return (
    <Badge variant="outline" className={cn('rounded-md whitespace-normal', TONE_CLASS[tone], className)}>
      {children}
    </Badge>
  );
}

type Codes = {
  request: Schemas['RequestStatus'];
  quote: Schemas['QuoteStatus'];
  contract: Schemas['ContractStatus'];
  invoice: Schemas['InvoiceStatus'];
  act: Schemas['ActStatus'];
  delivery: Schemas['DeliveryStatus'];
  availability: Schemas['Availability'];
};

/** Бейдж статуса сущности контракта: подпись из `status.<entity>.<code>`, тон из `lib/status`. */
export function StatusBadge<E extends StatusEntity>({ entity, code }: { entity: E; code: Codes[E] }) {
  const { t } = useTranslation();
  return <ToneBadge tone={statusTone(entity, code)}>{t(statusLabelKey(entity, code))}</ToneBadge>;
}
