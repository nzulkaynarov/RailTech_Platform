import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAdminPulse, useAdminQueue } from '@/hooks/useAdmin';
import { usePlatformDashboard } from '@/hooks/usePageStats';
import { ActivityFeed } from '@/components/PlatformAdmin/ActivityFeed';
import { PulseCards } from '@/components/PlatformAdmin/PulseCards';
import { QueueConfirmDialogs } from '@/components/PlatformAdmin/QueueConfirmDialogs';
import { SummaryPanel } from '@/components/PlatformAdmin/SummaryPanel';
import { TriageQueuePanel } from '@/components/PlatformAdmin/TriageQueuePanel';
import { useQueueActions } from '@/components/PlatformAdmin/useQueueActions';

type PulsePeriod = '7d' | '30d' | '90d';

interface PlatformAdminDashboardProps {
  onNavigate: (target: string) => void;
}

/**
 * Дашборд Platform Operator: пульс платформы за период, очередь триажа (что требует решения
 * сейчас), лента событий и сводка-навигация. Страница — композиция; каждая панель и слой
 * действий живут в `components/PlatformAdmin/`.
 */
export default function PlatformAdminDashboard({ onNavigate }: PlatformAdminDashboardProps): React.ReactNode {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<PulsePeriod>('30d');
  const [queueFilter, setQueueFilter] = useState<string>('');

  const queue = useAdminQueue(queueFilter || undefined);
  const pulse = useAdminPulse(period);
  const dashboard = usePlatformDashboard();
  const actions = useQueueActions(onNavigate);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">{t('platformAdmin.dashboard.title')}</h1>
          <p className="text-xs text-muted-foreground">{t('platformAdmin.dashboard.subtitle')}</p>
        </div>
        <Tabs value={period} onValueChange={(v) => setPeriod(v as PulsePeriod)}>
          <TabsList className="h-8">
            <TabsTrigger value="7d" className="text-xs">{t('common.period7d')}</TabsTrigger>
            <TabsTrigger value="30d" className="text-xs">{t('common.period30d')}</TabsTrigger>
            <TabsTrigger value="90d" className="text-xs">{t('common.period90d')}</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <PulseCards pulse={pulse.data} isLoading={pulse.isLoading} />

      <TriageQueuePanel
        items={queue.data?.items ?? []}
        totals={queue.data?.totals ?? {}}
        filter={queueFilter}
        onFilterChange={setQueueFilter}
        // Спиннер только на ПЕРВОЙ загрузке: при смене фильтра `placeholderData` держит
        // прежние строки, и подменять их спиннером значило бы моргать списком.
        isLoading={queue.isLoading && !queue.data}
        isError={queue.isError}
        onRetry={() => queue.refetch()}
        onOpen={actions.handleOpen}
        onApprove={actions.handleApprove}
        onReject={actions.handleReject}
      />

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <ActivityFeed
          entries={dashboard.data?.recent_activity ?? []}
          isLoading={dashboard.isLoading}
          isError={dashboard.isError}
          onRetry={() => dashboard.refetch()}
        />
        <SummaryPanel dashboard={dashboard.data} onNavigate={onNavigate} />
      </div>

      <QueueConfirmDialogs
        confirm={actions.confirm}
        onClose={() => actions.setConfirm(null)}
        onConfirm={actions.runConfirm}
      />
    </div>
  );
}
