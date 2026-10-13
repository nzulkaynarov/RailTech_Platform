/**
 * Соответствие «код статуса → вариант бейджа». Отдельный модуль, а не соседство с
 * `StatusBadge`: файл-компонент, экспортирующий ещё и хелперы, ломает Fast Refresh
 * (react-refresh/only-export-components), а Vite dev-сервер в проекте используется
 * (Docs/dev/ops/docker-setup.md).
 */

import type { BadgeVariant } from '@/components/ui/StatusBadge';

const stockVariantMap: Record<string, BadgeVariant> = {
  IN_STOCK: 'success',
  ON_ORDER: 'warning',
  EXPECTED: 'info',
  OUT_OF_STOCK: 'danger',
};
const dealStageVariantMap: Record<string, BadgeVariant> = {
  DRAFT: 'neutral',
  KYC_PENDING: 'warning',
  SOURCING: 'info',
  CALCULATING: 'info',
  QUOTE_SENT: 'warning',
  CONTRACT_SIGNED: 'success',
  CLOSED_WON: 'success',
  CLOSED_LOST: 'danger',
};
const kycVariantMap: Record<string, BadgeVariant> = {
  L1_UNVERIFIED: 'warning',
  L2_VERIFIED: 'success',
  L3_CONTRACTED: 'success',
};

export function getStockVariant(status: string): BadgeVariant {
  return stockVariantMap[status] ?? 'neutral';
}

export function getDealStageVariant(stage: string): BadgeVariant {
  return dealStageVariantMap[stage] ?? 'neutral';
}

export function getKycVariant(status: string): BadgeVariant {
  return kycVariantMap[status] ?? 'neutral';
}
