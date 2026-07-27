import type { TFunction } from 'i18next';

import { DealStage } from '@/lib/codes';

/**
 * W3 (spec-inbound-rfq, aging-counters — Bitrix24 pattern): how long a заявка has been
 * waiting for a seller. Pure client-side math over fields the Deal serializer already
 * exposes (created_at / assigned_to / stage_code) — no backend round-trip.
 */

/** Стадии «заявка ждёт КП» — до отправки предложения. */
export const PRE_KP_STAGES: string[] = [DealStage.RFQ_OPEN, DealStage.SOURCING, DealStage.CALCULATING];

const HOUR_MS = 3_600_000;

/** Full hours since `createdAt`; null when the timestamp is missing/unparseable. */
export function waitingHours(createdAt?: string | null): number | null {
  if (!createdAt) return null;
  const started = new Date(createdAt).getTime();
  if (!Number.isFinite(started)) return null;
  return Math.max(0, Math.floor((Date.now() - started) / HOUR_MS));
}

/** «ждёт 3 ч» / «ждёт 2 дн.» — null когда возраст неизвестен. */
export function formatWaiting(t: TFunction, createdAt?: string | null): string | null {
  const hours = waitingHours(createdAt);
  if (hours == null) return null;
  if (hours < 24) return t('deals.waitingHours', { count: hours });
  return t('deals.waitingDays', { count: Math.floor(hours / 24) });
}

/** Непринятая заявка в пред-КП стадии — то, что зовёт продавца в очередь. */
export function isUnclaimedRfq(deal: { stage_code?: string | null; assigned_to?: number | null }): boolean {
  return deal.assigned_to == null && PRE_KP_STAGES.includes(deal.stage_code ?? '');
}
