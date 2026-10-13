import { useTranslation } from 'react-i18next';
import { AlertTriangle, Loader2, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { AdminQueueItem } from '@/api/adminApi';
import { QueueRow } from './QueueRow';

export interface TriageQueuePanelProps {
  items: AdminQueueItem[];
  totals: Record<string, number>;
  filter: string;
  onFilterChange: (value: string) => void;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  onOpen: (item: AdminQueueItem) => void;
  onApprove: (item: AdminQueueItem) => void;
  onReject: (item: AdminQueueItem) => void;
}

/**
 * Очередь триажа оператора — центральная панель дашборда: что требует решения прямо сейчас.
 * Фильтр по типу очереди строится из `totals`, приходящих с сервера, поэтому новый тип
 * появляется в выпадающем списке сам, без правки фронта.
 */
export function TriageQueuePanel({
  items,
  totals,
  filter,
  onFilterChange,
  isLoading,
  isError,
  onRetry,
  onOpen,
  onApprove,
  onReject,
}: TriageQueuePanelProps) {
  const { t } = useTranslation();

  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-3 pb-2">
        <CardTitle className="text-sm">
          {t('platformAdmin.queue.title')}
          <span className="ml-2 text-xs text-muted-foreground">({items.length})</span>
        </CardTitle>
        <Select value={filter || 'all'} onValueChange={(v) => onFilterChange(v === 'all' ? '' : v)}>
          <SelectTrigger className="ml-auto h-7 w-48 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">{t('platformAdmin.queue.filters.all')}</SelectItem>
            {Object.keys(totals).map((qt) => (
              <SelectItem key={qt} value={qt} className="text-xs">
                {t(`platformAdmin.queue.filters.${qt}`, { defaultValue: qt })}
                <span className="ml-1 text-muted-foreground">· {totals[qt]}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </CardHeader>
      <CardContent className="p-0">
        {isError ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <AlertTriangle className="h-5 w-5 text-destructive" aria-hidden="true" />
            <div className="text-xs font-medium text-foreground">{t('common.loadError')}</div>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onRetry}>
              {t('common.retry')}
            </Button>
          </div>
        ) : isLoading ? (
          <div className="flex justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center gap-1 py-10 text-center text-xs text-muted-foreground">
            <ShieldCheck className="h-5 w-5 text-success" />
            <div className="font-medium">{t('platformAdmin.queue.emptyTitle')}</div>
            <div>{t('platformAdmin.queue.emptyHint')}</div>
          </div>
        ) : (
          <div className="divide-y">
            {items.map((item) => (
              <QueueRow
                key={`${item.queue_type}:${item.entity_id}`}
                item={item}
                onOpen={onOpen}
                onApprove={onApprove}
                onReject={onReject}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
