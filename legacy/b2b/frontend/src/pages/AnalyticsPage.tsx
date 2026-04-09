import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { BarChart3 } from 'lucide-react';
import { useUserStore } from '@/store/userStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { usePageStats } from '@/hooks/usePageStats';
import { useAnalytics } from '@/hooks/useCRM';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';

function BuyerAnalytics() {
  const { t } = useTranslation();
  const { data: ps } = usePageStats();

  return (
    <PageShell
      title={t('pages.analytics.buyerTitle')}
      description={t('pages.analytics.buyerDescription')}
      icon={<BarChart3 className="h-5 w-5" />}
      stats={[
        { label: t('pages.analytics.buyerStats.spendPeriod'), value: ps?.analytics_buyer?.spend_period ?? '—' },
        { label: t('pages.analytics.buyerStats.savings'), value: ps?.analytics_buyer?.savings ?? '—' },
        { label: t('pages.analytics.buyerStats.activeRequests'), value: String(ps?.analytics_buyer?.active_requests ?? '—') },
        { label: t('pages.analytics.buyerStats.avgDelivery'), value: '—' },
      ]}
    >
      <EmptyState icon={<BarChart3 className="h-5 w-5" />} message={t('pages.common.sectionInDevelopment')} />
    </PageShell>
  );
}

export function AnalyticsPage() {
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  const { activeStatus } = useUserStore();
  const { data: analytics, isLoading } = useAnalytics();
  const formatCurrency = useCurrencyStore((s) => s.format);

  if (activeStatus === 'BUYER') {
    return <BuyerAnalytics />;
  }

  const funnelData = (analytics?.pipeline_by_status ?? []).map((item) => ({
    stage: item.stage__name,
    value: item.count,
  }));
  const maxFunnel = Math.max(...funnelData.map((d) => d.value), 1);

  const chartColorClasses = ['bg-[var(--color-chart-1)]', 'bg-[var(--color-chart-2)]', 'bg-[var(--color-chart-5)]', 'bg-[var(--color-chart-4)]', 'bg-[var(--color-chart-3)]'];

  return (
    <PageShell
      title={activeStatus === 'MANUFACTURER' ? t('pages.analytics.manufacturerTitle') : t('pages.analytics.sellerTitle')}
      description={activeStatus === 'MANUFACTURER' ? t('pages.analytics.manufacturerDescription') : t('pages.analytics.sellerDescription')}
      icon={<BarChart3 className="h-5 w-5" />}
      stats={[
        { label: t('pages.analytics.stats.conversion'), value: analytics?.conversion_rate != null ? `${analytics.conversion_rate.toFixed(1)}%` : (ps?.analytics?.conversion ?? '—') },
        { label: t('pages.analytics.stats.avgDeal'), value: analytics?.avg_margin != null ? `${analytics.avg_margin.toFixed(1)}%` : (ps?.analytics?.avg_deal ?? '—') },
        { label: t('pages.analytics.stats.pipeline'), value: analytics?.total_pipeline_value != null ? formatCurrency(analytics.total_pipeline_value) : (ps?.analytics?.pipeline ?? '—') },
        { label: t('pages.analytics.stats.winRate'), value: ps?.analytics?.win_rate ?? '—' },
      ]}
    >
      {isLoading ? <LoadingRows rows={4} /> : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('pages.analytics.conversionFunnel')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {funnelData.length === 0 ? (
                <EmptyState icon={<BarChart3 className="h-5 w-5" />} message={t('pages.common.noData')} />
              ) : funnelData.map((item, idx) => {
                const percentage = (item.value / maxFunnel) * 100;
                return (
                  <div key={idx} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="font-medium">{item.stage}</span>
                      <span className="text-muted-foreground">{item.value}</span>
                    </div>
                    <div className="h-8 rounded-full overflow-hidden bg-muted">
                      <div
                        className={cn('h-full rounded-full flex items-center justify-end pr-2 text-xs font-medium text-primary-foreground', chartColorClasses[idx % chartColorClasses.length])}
                        style={{ width: `${Math.max(percentage, 5)}%` }}
                      >
                        {percentage > 20 && item.value}
                      </div>
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('pages.analytics.keyMetrics')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">{t('pages.analytics.sourcingBacklog')}</p>
                  <p className="text-2xl font-bold tabular-nums">{analytics?.sourcing_backlog ?? 0}</p>
                </div>
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">{t('pages.analytics.kycBacklog')}</p>
                  <p className="text-2xl font-bold tabular-nums">{analytics?.kyc_backlog ?? 0}</p>
                </div>
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">{t('pages.analytics.mappedItems')}</p>
                  <p className="text-2xl font-bold tabular-nums">{analytics?.mapped_items_percentage != null ? `${analytics.mapped_items_percentage.toFixed(0)}%` : '—'}</p>
                </div>
                <div className="rounded-lg border p-4">
                  <p className="text-xs text-muted-foreground">{t('pages.analytics.sourcingSpeed')}</p>
                  <p className="text-2xl font-bold tabular-nums">{analytics?.sourcing_speed_avg != null ? `${analytics.sourcing_speed_avg.toFixed(1)}${t('common.unitHours')}` : '—'}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </PageShell>
  );
}

export default AnalyticsPage;
