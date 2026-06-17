import { DealStage } from '@/lib/codes';

/**
 * Buyer-facing request status — collapses the 9 internal deal stages into the
 * handful a buyer actually cares about (the rest are seller-internal workflow).
 * World-standard RFQ status model (Draft → Awaiting quote → Quote received →
 * Confirmed → Completed/Cancelled), à la Ariba / Amazon Business / Alibaba RFQ.
 */
export type BuyerStatusKey =
  | 'draft'
  | 'awaiting'
  | 'quote'
  | 'confirmed'
  | 'completed'
  | 'cancelled';

type BadgeVariant = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

const STAGE_TO_BUYER: Record<string, BuyerStatusKey> = {
  [DealStage.DRAFT]: 'draft',
  [DealStage.KYC_PENDING]: 'awaiting',
  [DealStage.RFQ_OPEN]: 'awaiting',
  [DealStage.SOURCING]: 'awaiting',
  [DealStage.CALCULATING]: 'awaiting',
  [DealStage.QUOTE_SENT]: 'quote',
  [DealStage.CONTRACT_SIGNED]: 'confirmed',
  [DealStage.CLOSED_WON]: 'completed',
  [DealStage.CLOSED_LOST]: 'cancelled',
};

const VARIANT: Record<BuyerStatusKey, BadgeVariant> = {
  draft: 'neutral',
  awaiting: 'info',
  quote: 'warning', // action needed: accept / reject the КП
  confirmed: 'info',
  completed: 'success',
  cancelled: 'danger',
};

// Order for the status-filter tabs.
export const BUYER_STATUS_ORDER: BuyerStatusKey[] = [
  'draft',
  'awaiting',
  'quote',
  'confirmed',
  'completed',
  'cancelled',
];

export function buyerStatusKey(stageCode?: string | null): BuyerStatusKey {
  return STAGE_TO_BUYER[stageCode ?? ''] ?? 'draft';
}

export function buyerStatus(stageCode?: string | null): { key: BuyerStatusKey; labelKey: string; variant: BadgeVariant } {
  const key = buyerStatusKey(stageCode);
  return { key, labelKey: `requestStatus.${key}`, variant: VARIANT[key] };
}
