import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { activityDetail, activityTitle } from '@/lib/activityText';
import type { PlatformDashboard } from '@/api/dashboardApi';

type ActivityEntry = PlatformDashboard['recent_activity'][number];

/** Сколько последних записей показывать — лента дашборда, а не полный журнал (он в #admin-access-log). */
const VISIBLE_ENTRIES = 15;

export interface ActivityFeedProps {
  entries: ActivityEntry[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}

/** Лента последних событий платформы. Тексты локализуются через общий activityText. */
export function ActivityFeed({ entries, isLoading, isError, onRetry }: ActivityFeedProps) {
  const { t, i18n } = useTranslation();

  return (
    <Card className="md:col-span-2">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{t('platformAdmin.activity.title')}</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {isError ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <AlertTriangle className="h-4 w-4 text-destructive" aria-hidden="true" />
            <div className="text-xs font-medium text-foreground">{t('common.loadError')}</div>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onRetry}>
              {t('common.retry')}
            </Button>
          </div>
        ) : isLoading && entries.length === 0 ? (
          <div className="flex justify-center p-6">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        ) : entries.length === 0 ? (
          <div className="px-4 py-6 text-center text-xs text-muted-foreground">
            {t('platformAdmin.activity.empty')}
          </div>
        ) : (
          <ul className="divide-y text-xs">
            {entries.slice(0, VISIBLE_ENTRIES).map((entry) => {
              const detail = activityDetail(t, i18n, entry);
              return (
                <li key={entry.id} className="flex items-start justify-between gap-3 px-4 py-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant={
                          entry.level === 'ERROR'
                            ? 'destructive'
                            : entry.level === 'WARNING'
                              ? 'secondary'
                              : 'outline'
                        }
                        className="text-xs"
                      >
                        {entry.level}
                      </Badge>
                      <span className="font-medium">{activityTitle(t, i18n, entry)}</span>
                    </div>
                    {detail ? <div className="mt-0.5 truncate text-muted-foreground">{detail}</div> : null}
                    {entry.user_email ? (
                      <div className="mt-0.5 text-muted-foreground">{entry.user_email}</div>
                    ) : null}
                  </div>
                  <time className="shrink-0 text-muted-foreground" dateTime={entry.timestamp}>
                    {new Date(entry.timestamp).toLocaleDateString([], {
                      day: '2-digit',
                      month: 'short',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </time>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
