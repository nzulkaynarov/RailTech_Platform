import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';

interface PageShellProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  // onClick turns a KPI tile into a filter shortcut (reframes the tiles as
  // filters, not a total — so a subset of statuses no longer reads as "the sum
  // doesn't add up"). `active` highlights the currently-applied filter.
  stats?: { label: string; value: string; onClick?: () => void; active?: boolean }[];
  actions?: { label: string; variant?: 'default' | 'outline'; onClick?: () => void }[];
  children?: React.ReactNode;
}

export function PageShell({ title, description, icon, stats, actions, children }: PageShellProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">{icon}</div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
        </div>
        {actions && (
          <div className="flex gap-2">
            {actions.map((a, i) => (
              <Button key={i} variant={a.variant ?? 'default'} onClick={a.onClick}>{a.label}</Button>
            ))}
          </div>
        )}
      </div>
      {stats && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {stats.map((s) => (
            <Card
              key={s.label}
              onClick={s.onClick}
              role={s.onClick ? 'button' : undefined}
              tabIndex={s.onClick ? 0 : undefined}
              onKeyDown={s.onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); s.onClick!(); } } : undefined}
              className={`py-4 gap-1 ${s.onClick ? 'cursor-pointer transition-colors hover:bg-muted/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring' : ''} ${s.active ? 'border-primary ring-1 ring-primary' : ''}`}
            >
              <CardContent className="px-4">
                <p className="text-xs text-muted-foreground">{s.label}</p>
                <p className="text-2xl font-bold tabular-nums">{s.value}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      {children ?? (
        <Card>
          <CardContent className="flex h-64 items-center justify-center">
            <div className="text-center text-muted-foreground">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">{icon}</div>
              <p className="text-sm font-medium">{t('pages.common.sectionInDevelopment')}</p>
              <p className="mt-1 text-xs">{t('pages.common.comingSoon')}</p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export function LoadingRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

interface EmptyStateProps {
  icon: React.ReactNode;
  message: string;
  /** Optional secondary explanation below the main message — why this list
   * is empty and what the user should do next. */
  hint?: string;
  /** Optional inline call-to-action. Label + click handler.
   * Used to close the "empty list without next step" UX dead-end. */
  action?: { label: string; onClick: () => void };
}

export function EmptyState({ icon, message, hint, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">{icon}</div>
      <p className="text-sm font-medium text-foreground">{message}</p>
      {hint && <p className="mt-1 max-w-sm text-xs text-muted-foreground">{hint}</p>}
      {action && (
        <Button className="mt-4" size="sm" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}

/** Distinct from EmptyState: a failed fetch must not read as "nothing here". */
export function ErrorState({ onRetry }: { onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
        <AlertTriangle className="h-6 w-6 text-destructive" aria-hidden="true" />
      </div>
      <p className="text-sm font-medium text-foreground">{t('common.loadError')}</p>
      {onRetry && (
        <Button className="mt-4" size="sm" variant="outline" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  );
}
