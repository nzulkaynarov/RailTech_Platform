import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { activityTitle, activityDetail } from '@/lib/activityText';
import { useAdminActivity } from '@/hooks/useAdmin';
import type { AdminActivityEntry } from '@/api/adminApi';

/**
 * Запрос идёт через `useAdminActivity` и типизированный api-клиент. Раньше компонент собирал
 * тот же запрос ИНЛАЙНОМ, с тем же ключом кэша, что и хук: две реализации одного чтения, из
 * которых вызывалась только одна, а вторая числилась мёртвой. Форма записи тоже дублировалась
 * — теперь берётся из контракта (`AdminActivityEntry`).
 */
export type ActivityEntry = AdminActivityEntry;

interface AdminActivityTimelineProps {
  entityType: string;
  entityId: number | string;
  limit?: number;
}

const LEVEL_STYLES: Record<ActivityEntry['level'], string> = {
  INFO: 'bg-info/10 text-info border-info/30',
  SUCCESS: 'bg-success/10 text-success border-success/30',
  WARNING: 'bg-warning/10 text-warning border-warning/30',
  ERROR: 'bg-destructive/10 text-destructive border-destructive/30',
};

function formatTimestamp(iso: string): string {
  try {
    const date = new Date(iso);
    return date.toLocaleString([], {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function diffRows(before: ActivityEntry['before_data'], after: ActivityEntry['after_data']) {
  if (!before && !after) return [];
  const keys = Array.from(
    new Set([
      ...Object.keys(before ?? {}),
      ...Object.keys(after ?? {}),
    ]),
  );
  return keys.map((k) => ({
    key: k,
    before: before ? String(before[k] ?? '') : '',
    after: after ? String(after[k] ?? '') : '',
  }));
}

export function AdminActivityTimeline({
  entityType,
  entityId,
  limit = 100,
}: AdminActivityTimelineProps): React.ReactNode {
  const { t, i18n } = useTranslation();
  const { data, isLoading, isError, refetch } = useAdminActivity(entityType, entityId, limit);

  // Упавший журнал аудита — не «действий не было». Для истории записи это опаснее обычного:
  // оператор принимает решение, считая, что с объектом ничего не делали (класс волны U2).
  if (isError) {
    return (
      <Card className="flex flex-col items-center gap-2 p-6 text-center">
        <AlertTriangle className="h-4 w-4 text-destructive" aria-hidden="true" />
        <p className="text-xs font-medium text-foreground">{t('common.loadError')}</p>
        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => refetch()}>
          {t('common.retry')}
        </Button>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    );
  }

  const items = data?.items ?? [];

  if (items.length === 0) {
    return (
      <Card className="p-6 text-center text-xs text-muted-foreground">
        {t('adminDetail.timelineEmpty')}
      </Card>
    );
  }

  return (
    <Card className="divide-y">
      {items.map((entry) => {
        const diffs = diffRows(entry.before_data, entry.after_data);
        return (
          <div key={entry.id} className="flex flex-col gap-1 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className={cn('text-xs', LEVEL_STYLES[entry.level])}
              >
                {entry.level}
              </Badge>
              <span className="text-xs font-medium">{activityTitle(t, i18n, entry)}</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {formatTimestamp(entry.timestamp)}
              </span>
            </div>
            {activityDetail(t, i18n, entry) ? (
              <div className="text-xs text-muted-foreground">{activityDetail(t, i18n, entry)}</div>
            ) : null}
            {entry.user_email ? (
              <div className="text-xs text-muted-foreground">
                {entry.user_name || entry.user_email}
              </div>
            ) : null}
            {entry.reason ? (
              <div className="mt-1 rounded border border-dashed border-warning/40 bg-warning/5 p-2 text-xs">
                <span className="font-medium text-warning">
                  {t('adminDetail.reason')}:
                </span>{' '}
                {entry.reason}
              </div>
            ) : null}
            {diffs.length > 0 ? (
              <ul className="mt-1 space-y-0.5 text-xs">
                {diffs.map((d) => (
                  <li key={d.key} className="flex items-start gap-2">
                    <span className="text-muted-foreground">{d.key}:</span>
                    {d.before ? (
                      <span className="text-destructive line-through">{d.before}</span>
                    ) : null}
                    {d.before && d.after ? <span>→</span> : null}
                    {d.after ? (
                      <span className="text-success">{d.after}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
    </Card>
  );
}
