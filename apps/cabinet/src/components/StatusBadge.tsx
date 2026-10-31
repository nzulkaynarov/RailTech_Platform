import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { statusLabelKey, statusTone, type StatusEntity, type StatusTone } from '@/lib/status';
import type { Schemas } from '@/api/portal';

/**
 * Тон → семантические токены палитры «Legal Eminence»:
 * мягкие полутона с четким контрастом и обязательной текстовой подписью.
 */
const TONE_CLASS: Record<StatusTone, string> = {
  success: 'border-transparent bg-sage-bg text-sage',
  warning: 'border-sand-border bg-sand-bg text-sand',
  danger: 'border-coral-border bg-coral-bg text-coral',
  info: 'border-transparent bg-ice-navy text-navy',
  neutral: 'border-hairline bg-alabaster text-muted-foreground',
};

export function ToneBadge({ tone, children, className }: { tone: StatusTone; children: React.ReactNode; className?: string }) {
  return (
    <Badge variant="outline" className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-normal', TONE_CLASS[tone], className)}>
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
