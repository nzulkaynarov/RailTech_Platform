import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { ClipboardList, FileSpreadsheet, ChevronRight } from 'lucide-react';
import { useDeals, useDealStages } from '@/hooks/useCRM';
import { usePageStats } from '@/hooks/usePageStats';
import { useCurrencyStore } from '@/store/currencyStore';
import { useFlowStore } from '@/store/flowStore';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import { Toolbar, Pager, useListParams, applyListParams } from '@/components/DataTable';
import type { Deal } from '@/api/crmApi';

const SOURCING_STAGES = new Set(['SOURCING', 'CALCULATING', 'DRAFT']);

export function SourcingRequestsPage({ onNavigate }: { onNavigate?: (t: string) => void }) {
  const { t } = useTranslation();
  const { data: ps } = usePageStats();
  const { data: deals, isLoading } = useDeals();
  const { data: stages } = useDealStages();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const s = ps?.sourcing;

  const listParams = useListParams(['stage'] as const, { defaultOrdering: '-created_at', pageSize: 15 });

  const sourcingDeals = (deals ?? []).filter((d: Deal) =>
    SOURCING_STAGES.has(d.stage_code ?? '')
  );

  return (
    <PageShell
      title={t('pages.sourcingRequests.title')}
      description={t('pages.sourcingRequests.description')}
      icon={<ClipboardList className="h-5 w-5" />}
      stats={[
        { label: t('pages.sourcingRequests.stats.total'), value: String(s?.total ?? sourcingDeals.length) },
        { label: t('pages.sourcingRequests.stats.new'), value: String(s?.new ?? sourcingDeals.filter(d => d.stage_code === 'DRAFT').length) },
        { label: t('pages.sourcingRequests.stats.inProgress'), value: String(s?.in_progress ?? sourcingDeals.filter(d => d.stage_code === 'SOURCING').length) },
        { label: t('pages.sourcingRequests.stats.completed'), value: String(s?.completed ?? sourcingDeals.filter(d => d.stage_code === 'CALCULATING').length) },
      ]}
      actions={[{ label: t('pages.sourcingRequests.createRequest'), onClick: () => onNavigate?.('products') }]}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('pages.sourcingRequests.searchPlaceholder')}
        filters={[
          {
            key: 'stage',
            value: listParams.filters.stage,
            onChange: (v) => listParams.setFilter('stage', v),
            allLabel: t('pages.sourcingRequests.allStages'),
            options: (stages ?? []).filter(s => SOURCING_STAGES.has(s.code)).map((s) => ({ value: s.code, label: s.name })),
          },
        ]}
      />

      {(() => {
        const { items: pageItems, total } = applyListParams(sourcingDeals, listParams, {
          searchFields: (d) => [d.title, d.client_name, d.company_name, String(d.id)],
          filterPredicates: {
            stage: (d, v) => d.stage_code === v,
          },
          sortAccessors: {
            created_at: (d) => d.created_at ?? '',
          },
        });
        if (isLoading) return <LoadingRows rows={3} />;
        if (!pageItems.length) return <EmptyState icon={<ClipboardList className="h-5 w-5" />} message={t('pages.common.noData')} />;
        return (
          <>
            <div className="space-y-2">
              {pageItems.map((deal: Deal) => (
                <Card key={deal.id} className="cursor-pointer hover:border-primary/50 transition-colors py-0 gap-0" onClick={() => { useFlowStore.getState().setActiveDealId(deal.id); onNavigate?.('request-detail'); }}>
                  <CardContent className="px-4 py-4">
                    <div className="flex items-center gap-4">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                        <FileSpreadsheet className="h-5 w-5 text-primary" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{deal.title ?? `#${deal.id}`}</span>
                          <Badge variant="outline" className="text-xs">{deal.stage_name}</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {deal.client_name || deal.company_name || ''}{deal.client_name || deal.company_name ? ' · ' : ''}{new Date(deal.created_at).toLocaleDateString()}
                        </p>
                      </div>
                      {deal.total_value ? (
                        <p className="text-sm font-bold text-primary tabular-nums">{formatCurrency(Number(deal.total_value))}</p>
                      ) : null}
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
            <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
          </>
        );
      })()}
    </PageShell>
  );
}

export default SourcingRequestsPage;
