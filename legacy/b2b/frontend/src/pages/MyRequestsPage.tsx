import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ShoppingCart, FileText, ChevronRight } from 'lucide-react';
import { useCurrencyStore } from '@/store/currencyStore';
import { usePageStats } from '@/hooks/usePageStats';
import { useDeals, useDealStages } from '@/hooks/useCRM';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import { Toolbar, Pager, useListParams, applyListParams } from '@/components/DataTable';
import type { Deal } from '@/api/crmApi';

export function MyRequestsPage({ onNavigate }: { onNavigate?: (t: string) => void }) {
  const { data: ps } = usePageStats();
  const { t } = useTranslation();
  const { data: deals, isLoading } = useDeals();
  const { data: stages } = useDealStages();
  const formatCurrency = useCurrencyStore((s) => s.format);

  const listParams = useListParams(['stage'] as const, { defaultOrdering: '-created_at', pageSize: 15 });
  const myDeals = deals ?? [];

  return (
    <PageShell
      title={t('pages.myRequests.title')}
      description={t('pages.myRequests.description')}
      icon={<ShoppingCart className="h-5 w-5" />}
      stats={[
        { label: t('pages.myRequests.stats.active'), value: String(ps?.my_requests?.active ?? myDeals.filter((d: Deal) => !['CLOSED_WON', 'CLOSED_LOST'].includes(d.stage_code ?? '')).length) },
        { label: t('pages.myRequests.stats.quoteReceived'), value: String(ps?.my_requests?.quote_received ?? myDeals.filter((d: Deal) => d.stage_code === 'QUOTE_SENT').length) },
        { label: t('pages.myRequests.stats.contract'), value: String(ps?.my_requests?.contract ?? myDeals.filter((d: Deal) => d.stage_code === 'CONTRACT_SIGNED').length) },
        { label: t('pages.myRequests.stats.completed'), value: String(ps?.my_requests?.completed ?? myDeals.filter((d: Deal) => d.stage_code === 'CLOSED_WON').length) },
      ]}
      actions={[{ label: t('pages.myRequests.newRequest'), onClick: () => onNavigate?.('products') }]}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('pages.myRequests.searchPlaceholder')}
        filters={[
          {
            key: 'stage',
            value: listParams.filters.stage,
            onChange: (v) => listParams.setFilter('stage', v),
            allLabel: t('pages.myRequests.allStages'),
            options: (stages ?? []).map((s) => ({ value: s.code, label: s.name })),
          },
        ]}
      />

      {(() => {
        const { items: pageItems, total } = applyListParams(myDeals, listParams, {
          searchFields: (d) => [d.title, d.company_name, String(d.id)],
          filterPredicates: {
            stage: (d, v) => d.stage_code === v,
          },
          sortAccessors: {
            created_at: (d) => d.created_at ?? '',
          },
        });
        if (isLoading) return <LoadingRows rows={3} />;
        if (!pageItems.length) return (
          <EmptyState
            icon={<ShoppingCart className="h-5 w-5" />}
            message={t('pages.common.noData')}
            action={{ label: t('pages.myRequests.newRequest'), onClick: () => onNavigate?.('products') }}
          />
        );
        return (
          <>
            <div className="space-y-2">
              {pageItems.map((deal: Deal) => (
                <Card key={deal.id} className="cursor-pointer hover:border-primary/50 transition-colors py-0 gap-0">
                  <CardContent className="px-4 py-4">
                    <div className="flex items-center gap-4">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                        <FileText className="h-5 w-5 text-primary" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{deal.title ?? `${t('pages.myRequests.deal')} #${deal.id}`}</span>
                          <Badge variant="outline" className="text-xs">{deal.stage_name}</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {deal.company_name ? `${deal.company_name} · ` : ''}{new Date(deal.created_at).toLocaleDateString()}
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

export default MyRequestsPage;
