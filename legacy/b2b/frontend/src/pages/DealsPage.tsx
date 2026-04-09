import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { FileText, Clock } from 'lucide-react';
import { dealStageLabels } from '@/store/flowStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { usePageStats } from '@/hooks/usePageStats';
import { useDeals } from '@/hooks/useCRM';
import { PageShell, LoadingRows } from './shared/PageShell';
import type { Deal } from '@/api/crmApi';

export function DealsPage() {
  const { t } = useTranslation();
  const { data: ps } = usePageStats();
  const { data: deals, isLoading } = useDeals();
  const formatCurrency = useCurrencyStore((s) => s.format);

  const stageOrder = Object.keys(dealStageLabels);

  const grouped = stageOrder.map((code) => ({
    code,
    label: t(dealStageLabels[code as keyof typeof dealStageLabels]) ?? code,
    deals: (deals ?? []).filter((d: Deal) => d.stage_code === code),
  }));

  return (
    <PageShell
      title={t('pages.deals.title')}
      description={t('pages.deals.description')}
      icon={<FileText className="h-5 w-5" />}
      stats={[
        { label: t('pages.deals.stats.total'), value: String(ps?.deals?.total ?? '—') },
        { label: t('pages.deals.stats.active'), value: String(ps?.deals?.active ?? '—') },
        { label: t('pages.deals.stats.quoteSent'), value: String(ps?.deals?.quote_sent ?? '—') },
        { label: t('pages.deals.stats.closedWon'), value: String(ps?.deals?.closed_won ?? '—') },
      ]}
      actions={[{ label: t('pages.deals.newDeal') }]}
    >
      {isLoading ? <LoadingRows rows={4} /> : (
        <div className="overflow-x-auto pb-4">
          <div className="flex gap-4 min-w-max">
            {grouped.map((column) => (
              <div key={column.code} className="flex-shrink-0 w-80">
                <div className={cn('rounded-lg p-4 space-y-3 bg-muted')}>
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-sm">{column.label}</h3>
                    <Badge variant="outline" className="text-xs">{column.deals.length}</Badge>
                  </div>
                  <div className="space-y-3">
                    {column.deals.length === 0 && (
                      <p className="text-xs text-muted-foreground text-center py-4">{t('pages.common.noData')}</p>
                    )}
                    {column.deals.map((deal: Deal) => (
                      <Card key={deal.id} className="cursor-pointer hover:shadow-md transition-shadow">
                        <CardContent className="p-3 space-y-2">
                          <div>
                            <p className="font-medium text-sm">{deal.title ?? `#${deal.id}`}</p>
                            <p className="text-xs text-muted-foreground">{deal.client_name ?? deal.company_name ?? '—'}</p>
                          </div>
                          <div className="flex items-center justify-between">
                            <p className="text-lg font-bold text-primary">{deal.total_value ? formatCurrency(Number(deal.total_value)) : '—'}</p>
                            <Badge variant="secondary" className="text-xs">{deal.stage_name}</Badge>
                          </div>
                          <p className="text-xs text-muted-foreground flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {new Date(deal.created_at).toLocaleDateString()}
                          </p>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </PageShell>
  );
}

export default DealsPage;
