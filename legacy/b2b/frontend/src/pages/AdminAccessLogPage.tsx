import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollText, Loader2, KeyRound, ShieldAlert } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useAccessLog } from '@/hooks/useAdmin';
import { activityTitle } from '@/lib/activityText';
import { PageShell, ErrorState } from './shared/PageShell';

/**
 * Access log / Break-glass (ADR-0004 G2). Platform-wide feed of break-glass grants and
 * force-override actions, so an operator's access to a tenant's private data is attributable.
 * Read-only; gated server-side + in the nav on `moderation.force_override`.
 */
export function AdminAccessLogPage() {
  const { t, i18n } = useTranslation();
  const { data, isLoading, isError, refetch } = useAccessLog(200);
  // Зависимость мемо — САМ `data?.items` (ссылка из кэша React Query, стабильная между
  // рендерами), а не `?? []`: литерал пересоздавался каждый рендер и мемо не работало вовсе.
  const items = useMemo(() => data?.items ?? [], [data?.items]);

  const stats = useMemo(() => {
    const activeBreakGlass = items.filter((entry) => entry.is_break_glass && entry.is_active).length;
    const forceOverrides = items.filter((entry) => !entry.is_break_glass).length;
    return [
      { label: t('accessLogPage.stats.activeBreakGlass'), value: String(activeBreakGlass) },
      { label: t('accessLogPage.stats.forceOverrides'), value: String(forceOverrides) },
    ];
  }, [items, t]);

  const fmt = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' }) : '—';

  return (
    <PageShell
      title={t('accessLogPage.title')}
      description={t('accessLogPage.description')}
      icon={<ScrollText className="h-5 w-5" />}
      stats={stats}
    >
      {isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : isLoading ? (
        <div className="flex justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-hidden="true" />
        </div>
      ) : items.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted-foreground">{t('accessLogPage.empty')}</p>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-border">
          <Table>
            <TableHeader>
              <TableRow className="border-b border-border bg-muted/50 text-xs">
                <TableHead className="p-4">{t('accessLogPage.col.event')}</TableHead>
                <TableHead className="p-4">{t('accessLogPage.col.operator')}</TableHead>
                <TableHead className="p-4">{t('accessLogPage.col.entity')}</TableHead>
                <TableHead className="p-4">{t('accessLogPage.col.reason')}</TableHead>
                <TableHead className="p-4">{t('accessLogPage.col.when')}</TableHead>
                <TableHead className="p-4">{t('accessLogPage.col.status')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((entry) => (
                <TableRow key={entry.id} className="transition-colors hover:bg-muted/40">
                  <TableCell className="p-4">
                    <div className="flex items-center gap-2">
                      {entry.is_break_glass ? (
                        <KeyRound className="h-4 w-4 text-warning" aria-hidden="true" />
                      ) : (
                        <ShieldAlert className="h-4 w-4 text-destructive" aria-hidden="true" />
                      )}
                      <span className="text-sm font-medium text-foreground">{activityTitle(t, i18n, entry)}</span>
                    </div>
                  </TableCell>
                  <TableCell className="p-4">
                    <span className="text-sm text-muted-foreground">
                      {entry.user_name?.trim() || entry.user_email || '—'}
                    </span>
                  </TableCell>
                  <TableCell className="p-4">
                    <span className="font-mono text-xs text-muted-foreground">
                      {entry.entity_type ? `${entry.entity_type} #${entry.entity_id}` : '—'}
                    </span>
                  </TableCell>
                  <TableCell className="max-w-xs p-4">
                    <span className="text-sm text-muted-foreground">{entry.reason || '—'}</span>
                  </TableCell>
                  <TableCell className="p-4">
                    <span className="text-xs tabular-nums text-muted-foreground">{fmt(entry.timestamp)}</span>
                  </TableCell>
                  <TableCell className="p-4">
                    {entry.is_break_glass ? (
                      entry.is_active ? (
                        <Badge variant="secondary" className="text-xs">
                          {t('accessLogPage.badge.activeUntil', { time: fmt(entry.expires_at) })}
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-xs text-muted-foreground">
                          {t('accessLogPage.badge.expired')}
                        </Badge>
                      )
                    ) : (
                      <Badge variant="outline" className="text-xs">
                        {t('accessLogPage.badge.override')}
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </PageShell>
  );
}

export default AdminAccessLogPage;
