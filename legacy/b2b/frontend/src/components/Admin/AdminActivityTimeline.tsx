import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { apiClient } from '@/api/client';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

export interface ActivityEntry {
  id: number;
  action: string;
  detail: string;
  level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR';
  reason: string;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  user_id: number | null;
  user_email: string | null;
  user_name: string;
  timestamp: string;
}

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
    const d = new Date(iso);
    return d.toLocaleString([], {
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
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['admin-activity', entityType, entityId, limit],
    queryFn: async () => {
      const res = await apiClient.get<{
        count: number;
        items: ActivityEntry[];
      }>('admin/activity/', {
        params: { entity_type: entityType, entity_id: entityId, limit },
      });
      return res.data;
    },
    enabled: Boolean(entityType) && entityId !== undefined && entityId !== null,
    staleTime: 15_000,
  });

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
              <span className="text-xs font-medium">{entry.action}</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {formatTimestamp(entry.timestamp)}
              </span>
            </div>
            {entry.detail ? (
              <div className="text-xs text-muted-foreground">{entry.detail}</div>
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
