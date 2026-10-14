import { DealStage } from '@/lib/codes';

/**
 * Buyer-facing request status — collapses the 8 internal deal stages into the
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

/**
 * Статус заявки глазами ПОКУПАТЕЛЯ.
 *
 * O4 (18-08): «сделка выиграна» и «заказ исполнен» — разные шкалы. `CLOSED_WON` наступает при
 * подписании договора, когда покупателю ещё платить и принимать поставку, поэтому сам по себе
 * он даёт «В исполнении», а не «Завершено». Слово «Завершено» появляется, только когда сервер
 * подтвердил закрытую цепочку (`execution_complete`: счёт оплачен, поставка принята, акт
 * подписан) — это ровно граница, которую держат Odoo (Lock поверх Sales Order), Salesforce
 * (Opportunity → Order) и HubSpot (сделка → Invoice paid).
 */
export function buyerStatusKey(stageCode?: string | null, executionComplete?: boolean): BuyerStatusKey {
  const key = STAGE_TO_BUYER[stageCode ?? ''] ?? 'draft';
  if (key === 'completed' && !executionComplete) return 'confirmed';
  return key;
}

export function buyerStatus(
  stageCode?: string | null,
  executionComplete?: boolean,
): { key: BuyerStatusKey; labelKey: string; variant: BadgeVariant } {
  const key = buyerStatusKey(stageCode, executionComplete);
  return { key, labelKey: `requestStatus.${key}`, variant: VARIANT[key] };
}
