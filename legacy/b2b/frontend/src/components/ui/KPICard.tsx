import React from 'react';
import { cn } from '@/lib/utils';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { useTranslation } from 'react-i18next';

type TrendDirection = 'up' | 'down' | 'flat';

interface KPICardProps {
  label: string;
  value: string | number;
  icon?: React.ReactNode;
  trend?: {
    value: string;
    direction: TrendDirection;
  };
  href?: string;
  isLoading?: boolean;
  className?: string;
}

const trendStyles: Record<TrendDirection, string> = {
  up: 'text-success',
  down: 'text-destructive',
  flat: 'text-muted-foreground',
};

const TrendIcon: React.FC<{ direction: TrendDirection }> = ({ direction }) => {
  const size = 14;
  switch (direction) {
    case 'up': return <TrendingUp size={size} aria-hidden="true" />;
    case 'down': return <TrendingDown size={size} aria-hidden="true" />;
    case 'flat': return <Minus size={size} aria-hidden="true" />;
  }
};

const trendA11yKeys: Record<TrendDirection, string> = {
  up: 'a11y.trendUp',
  down: 'a11y.trendDown',
  flat: 'a11y.trendFlat',
};

const TrendIndicator: React.FC<{ direction: TrendDirection; value: string }> = ({ direction, value }) => {
  const { t } = useTranslation();
  return (
    <div className={cn('flex items-center gap-1 mt-1.5 text-xs font-medium', trendStyles[direction])}>
      <TrendIcon direction={direction} />
      <span>{value}</span>
      <span className="sr-only">({t(trendA11yKeys[direction])})</span>
    </div>
  );
};

/**
 * Reusable KPI card with optional icon, trend indicator, and link.
 * Uses shadcn Card + Skeleton for container and loading states.
 */
export const KPICard: React.FC<KPICardProps> = ({
  label,
  value,
  icon,
  trend,
  href,
  isLoading,
  className,
}) => {
  if (isLoading) {
    return (
      <Card className={cn('py-4', className)}>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-8 w-8 rounded-lg" />
          </div>
          <Skeleton className="h-6 w-20" />
          <Skeleton className="h-3 w-16" />
        </CardContent>
      </Card>
    );
  }

  const cardContent = (
    <Card
      className={cn(
        'py-4 transition-colors',
        href && 'hover:border-primary/30 cursor-pointer',
        className,
      )}
    >
      <CardContent>
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            {label}
          </span>
          {icon && (
            <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center">
              {icon}
            </div>
          )}
        </div>

        <div className="text-xl font-bold text-foreground tracking-tight">
          {value}
        </div>

        {trend && (
          <TrendIndicator direction={trend.direction} value={trend.value} />
        )}
      </CardContent>
    </Card>
  );

  if (href) {
    return <a href={href} className="block">{cardContent}</a>;
  }

  return cardContent;
};
