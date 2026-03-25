import React from 'react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

type BadgeVariant = 'success' | 'warning' | 'danger' | 'info' | 'neutral';
type BadgeSize = 'sm' | 'md';

interface StatusBadgeProps {
  label: string;
  variant?: BadgeVariant;
  size?: BadgeSize;
  icon?: React.ReactNode;
  className?: string;
}

/**
 * Maps our domain variants to a shadcn base variant + custom color classes.
 * We use "outline" as the base since it provides a bordered, transparent-bg look
 * that pairs well with our custom color overrides.
 */
const variantStyles: Record<BadgeVariant, string> = {
  success: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20 dark:text-emerald-400 dark:border-emerald-500/30',
  warning: 'bg-amber-500/10 text-amber-700 border-amber-500/20 dark:text-amber-400 dark:border-amber-500/30',
  danger: 'bg-red-500/10 text-red-700 border-red-500/20 dark:text-red-400 dark:border-red-500/30',
  info: 'bg-blue-500/10 text-blue-700 border-blue-500/20 dark:text-blue-400 dark:border-blue-500/30',
  neutral: 'bg-muted text-muted-foreground border-border',
};

const sizeStyles: Record<BadgeSize, string> = {
  sm: 'px-1.5 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-xs',
};

/** Unified status badge for stock, deal stages, KYC, etc. */
export const StatusBadge: React.FC<StatusBadgeProps> = ({
  label,
  variant = 'neutral',
  size = 'sm',
  icon,
  className,
}) => {
  return (
    <Badge
      variant="outline"
      className={cn(
        'font-semibold rounded-md',
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
    >
      {icon && <span className="shrink-0">{icon}</span>}
      {label}
    </Badge>
  );
};

/* ─── Preset mapping helpers ─── */

const stockVariantMap: Record<string, BadgeVariant> = {
  IN_STOCK: 'success',
  ON_ORDER: 'warning',
  EXPECTED: 'info',
  OUT_OF_STOCK: 'danger',
};

export function getStockVariant(status: string): BadgeVariant {
  return stockVariantMap[status] ?? 'neutral';
}

const dealStageVariantMap: Record<string, BadgeVariant> = {
  NEW: 'info',
  QUOTING: 'info',
  NEGOTIATION: 'warning',
  CONTRACT_SIGNED: 'success',
  IN_DELIVERY: 'warning',
  CLOSED_WON: 'success',
  CLOSED_LOST: 'danger',
};

export function getDealStageVariant(stage: string): BadgeVariant {
  return dealStageVariantMap[stage] ?? 'neutral';
}

const kycVariantMap: Record<string, BadgeVariant> = {
  L1_UNVERIFIED: 'warning',
  L2_VERIFIED: 'success',
  L3_CONTRACTED: 'success',
};

export function getKycVariant(status: string): BadgeVariant {
  return kycVariantMap[status] ?? 'neutral';
}
