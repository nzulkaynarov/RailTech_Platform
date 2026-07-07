import { useTranslation } from 'react-i18next';
import { formatDistanceToNow } from 'date-fns';
import { ru, enUS } from 'date-fns/locale';
import { History, CheckCircle2, AlertTriangle, XCircle, Info } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useDealTimeline } from '@/hooks/useCRM';
import type { TimelineEntry } from '@/api/crmApi';

// CRM Phase A — read-only history feed for a deal (заявка → КП → контракт events).
// Data comes from the backend ActivityLog timeline links; rendering only, no mutations.

const LEVEL_ICON: Record<TimelineEntry['level'], typeof Info> = {
  INFO: Info,
  SUCCESS: CheckCircle2,
  WARNING: AlertTriangle,
  ERROR: XCircle,
};

const LEVEL_CLASS: Record<TimelineEntry['level'], string> = {
  INFO: 'text-muted-foreground',
  SUCCESS: 'text-success',
  WARNING: 'text-warning',
  ERROR: 'text-destructive',
};

export function DealTimeline({ dealId }: { dealId: number }) {
  const { t, i18n } = useTranslation();
  const { data: entries, isLoading } = useDealTimeline(dealId);
  const dateLocale = i18n.language?.startsWith('ru') ? ru : enUS;

  if (isLoading || !entries || entries.length === 0) {
    // The feed is supplementary context — an empty/failed load must not add noise to the page.
    return null;
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <History className="h-4 w-4 text-muted-foreground" />
          {t('timeline.title')}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="relative border-s border-border ms-2 space-y-4">
          {entries.map((entry) => {
            const Icon = LEVEL_ICON[entry.level] ?? Info;
            return (
              <li key={entry.id} className="ms-4">
                <span className="absolute -start-2 mt-1 flex h-4 w-4 items-center justify-center rounded-full bg-background">
                  <Icon className={`h-3.5 w-3.5 ${LEVEL_CLASS[entry.level] ?? LEVEL_CLASS.INFO}`} />
                </span>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <p className="text-sm font-medium text-foreground">{entry.action}</p>
                  <time className="text-xs text-muted-foreground">
                    {formatDistanceToNow(new Date(entry.timestamp), { addSuffix: true, locale: dateLocale })}
                  </time>
                </div>
                {entry.detail && <p className="text-xs text-muted-foreground mt-0.5">{entry.detail}</p>}
                {entry.user_name && <p className="text-xs text-muted-foreground/70 mt-0.5">{entry.user_name}</p>}
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}
