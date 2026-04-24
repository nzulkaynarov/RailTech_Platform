import { ReactNode } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';

export interface DetailKPIItem {
  label: ReactNode;
  value: ReactNode;
  icon?: ReactNode;
  hint?: ReactNode;
  tone?: 'default' | 'success' | 'warning' | 'destructive' | 'info';
}

const TONE_CSS: Record<NonNullable<DetailKPIItem['tone']>, string> = {
  default: 'text-foreground',
  success: 'text-success',
  warning: 'text-warning',
  destructive: 'text-destructive',
  info: 'text-info',
};

/**
 * Compact grid of KPI cards used at the top of admin detail views
 * (company overview, user overview, subscription overview, etc.).
 *
 * Pure shadcn Card + semantic tokens — no hex colors, no custom CSS.
 */
export function DetailKPIGrid({
  items,
  columns = 3,
  className,
}: {
  items: DetailKPIItem[];
  columns?: 2 | 3 | 4;
  className?: string;
}) {
  const gridCols =
    columns === 4 ? 'grid-cols-2 md:grid-cols-4'
      : columns === 3 ? 'grid-cols-2 md:grid-cols-3'
        : 'grid-cols-2';
  return (
    <div className={cn('grid gap-2', gridCols, className)}>
      {items.map((it, idx) => (
        <Card key={idx} className="border-muted/50">
          <CardContent className="flex flex-col gap-1 p-3">
            <div className="flex items-center gap-1.5">
              {it.icon ? <span className="text-muted-foreground">{it.icon}</span> : null}
              <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
                {it.label}
              </span>
            </div>
            <div className={cn('text-lg font-semibold tabular-nums', TONE_CSS[it.tone ?? 'default'])}>
              {it.value ?? '—'}
            </div>
            {it.hint ? (
              <div className="text-xs text-muted-foreground">{it.hint}</div>
            ) : null}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
