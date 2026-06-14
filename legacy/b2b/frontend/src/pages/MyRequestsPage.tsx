import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ShoppingCart, FileText, ChevronRight } from 'lucide-react';
import { useCurrencyStore } from '@/store/currencyStore';
import { useDeals, useDealStages } from '@/hooks/useCRM';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import { Toolbar, Pager, useListParams, applyListParams } from '@/components/DataTable';
import { CreateDealDialog } from '@/components/CRM/CreateDealDialog';
import { DealStage } from '@/lib/codes';
import type { Deal } from '@/api/crmApi';

export function MyRequestsPage() {
  const { t } = useTranslation();
  const { data: deals, isLoading } = useDeals();
  const { data: stages } = useDealStages();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const [createOpen, setCreateOpen] = useState(false);

  const listParams = useListParams(['stage'] as const, { defaultOrdering: '-created_at', pageSize: 15 });
  const myDeals = deals ?? [];

  // Counters computed directly from the same dataset the list renders — avoids
  // the "Completed: 1 but list shows 0 completed items" mismatch that page-stats
  // caused when the two endpoints disagreed on visibility.
  const closed: string[] = [DealStage.CLOSED_WON, DealStage.CLOSED_LOST];
  const stats = [
    { label: t('pages.myRequests.stats.active'), value: String(myDeals.filter((d) => !closed.includes(d.stage_code ?? '')).length) },
    { label: t('pages.myRequests.stats.quoteReceived'), value: String(myDeals.filter((d) => d.stage_code === DealStage.QUOTE_SENT).length) },
    { label: t('pages.myRequests.stats.contract'), value: String(myDeals.filter((d) => d.stage_code === DealStage.CONTRACT_SIGNED).length) },
    { label: t('pages.myRequests.stats.completed'), value: String(myDeals.filter((d) => d.stage_code === DealStage.CLOSED_WON).length) },
  ];

  const openDeal = (deal: Deal) => {
    // Param-based deep link; the detail page reads the id from the hash route.
    window.location.hash = `request-detail/${deal.id}`;
  };

  return (
    <PageShell
      title={t('pages.myRequests.title')}
      description={t('pages.myRequests.description')}
      icon={<ShoppingCart className="h-5 w-5" />}
      stats={stats}
      actions={[{ label: t('pages.myRequests.newRequest'), onClick: () => setCreateOpen(true) }]}
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
            action={{ label: t('pages.myRequests.newRequest'), onClick: () => setCreateOpen(true) }}
          />
        );
        return (
          <>
            <div className="space-y-2">
              {pageItems.map((deal: Deal) => (
                <Card
                  key={deal.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => openDeal(deal)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') openDeal(deal); }}
                  className="cursor-pointer hover:border-primary/50 transition-colors py-0 gap-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
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

      {/* Create a заявка directly (catalog cart OR Excel-import path) instead of
          dumping the buyer onto the (possibly empty) catalog. */}
      <CreateDealDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(dealId) => { window.location.hash = `request-detail/${dealId}`; }}
      />
    </PageShell>
  );
}

export default MyRequestsPage;
