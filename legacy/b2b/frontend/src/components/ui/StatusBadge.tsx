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
  success: 'bg-success/10 text-success border-success/20',
  warning: 'bg-warning/10 text-warning border-warning/20',
  danger: 'bg-destructive/10 text-destructive border-destructive/20',
  info: 'bg-info/10 text-info border-info/20',
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
  DRAFT: 'neutral',
  KYC_PENDING: 'warning',
  SOURCING: 'info',
  CALCULATING: 'info',
  QUOTE_SENT: 'warning',
  CONTRACT_SIGNED: 'success',
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
