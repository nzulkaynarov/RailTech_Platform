import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, Clock, Eye } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { StatusBadge, getDealStageVariant } from '@/components/ui/StatusBadge';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';
import { useCurrencyStore } from '@/store/currencyStore';
import { useUserStore } from '@/store/userStore';
import { useDeals, useDealStages } from '@/hooks/useCRM';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { CreateDealDialog } from '@/components/CRM/CreateDealDialog';
import { DealsKanban } from '@/components/CRM/DealsKanban';
import type { Deal } from '@/api/crmApi';

/* ─── Single canonical seller deal pipeline (ADR-0003 consolidation) ─────────
 * One index (list + Kanban) → ONE deal record (request-detail/<id>) → focused
 * КП builder (deal-quote/<id>). The old Sourcing→Requests list and the inline
 * DealDetailSheet were removed (duplicate surfaces on the same useDeals data).
 */
function openDeal(deal: Deal) {
  window.location.hash = `request-detail/${deal.id}`;
}

export function DealsPage() {
  const { t } = useTranslation();
  const { data: deals, isLoading, isError, refetch } = useDeals();
  const { data: stages } = useDealStages();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const activeStatus = useUserStore((s) => s.activeStatus);

  const listParams = useListParams(['stage'] as const, { defaultOrdering: '-created_at' });
  const [createOpen, setCreateOpen] = useState(false);
  const [view, setView] = useState<'list' | 'kanban'>(() => {
    try {
      return (localStorage.getItem('deals.view') as 'list' | 'kanban') || 'list';
    } catch { return 'list'; }
  });
  const setViewPersisted = (v: 'list' | 'kanban') => {
    setView(v);
    try { localStorage.setItem('deals.view', v); } catch { /* ignore */ }
  };

  const stats = [
    { label: t('pages.deals.stats.total'), value: String(deals?.length ?? 0) },
    { label: t('pages.deals.stats.active'), value: String(deals?.filter(d => !['CLOSED_WON', 'CLOSED_LOST'].includes(d.stage_code ?? '')).length ?? 0) },
    { label: t('pages.deals.stats.quoteSent'), value: String(deals?.filter(d => d.stage_code === 'QUOTE_SENT').length ?? 0) },
    { label: t('pages.deals.stats.closedWon'), value: String(deals?.filter(d => d.stage_code === 'CLOSED_WON').length ?? 0) },
  ];

  return (
    <PageShell
      title={t('pages.deals.title')}
      description={t('pages.deals.description')}
      icon={<FileText className="h-5 w-5" />}
      stats={stats}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('pages.deals.searchPlaceholder')}
        filters={[
          {
            key: 'stage',
            value: listParams.filters.stage,
            onChange: (v) => listParams.setFilter('stage', v),
            allLabel: t('pages.deals.allStages'),
            options: (stages ?? []).map((s) => ({ value: s.code, label: s.name })),
          },
        ]}
        newLabel={activeStatus === 'BUYER' ? t('createDeal.title') : undefined}
        onNew={activeStatus === 'BUYER' ? () => setCreateOpen(true) : undefined}
        extra={
          <div className="inline-flex rounded-md border p-0.5 text-xs">
            <button
              type="button"
              className={`rounded-sm px-2 py-1 ${view === 'list' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}
              onClick={() => setViewPersisted('list')}
            >
              {t('dealsKanban.list')}
            </button>
            <button
              type="button"
              className={`rounded-sm px-2 py-1 ${view === 'kanban' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}
              onClick={() => setViewPersisted('kanban')}
            >
              {t('dealsKanban.kanban')}
            </button>
          </div>
        }
      />
      <CreateDealDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={() => {
          // Keep user on deals list; dialog already routed to import if chosen.
        }}
      />

      {view === 'kanban' ? (
        <DealsKanban
          deals={deals ?? []}
          stages={stages}
          onOpen={openDeal}
        />
      ) : (
      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(deals ?? [], listParams, {
              searchFields: (d) => [d.title, d.client_name, d.company_name, String(d.id)],
              filterPredicates: {
                stage: (d, v) => d.stage_code === v,
              },
              sortAccessors: {
                id: (d) => d.id,
                title: (d) => d.title ?? '',
                client: (d) => d.client_name ?? d.company_name ?? '',
                stage: (d) => d.stage_name ?? '',
                value: (d) => Number(d.total_value) || 0,
                created_at: (d) => d.created_at ?? '',
              },
            });
            if (isLoading) return <LoadingRows rows={5} />;
            if (isError) return <ErrorState onRetry={refetch} />;
            if (!pageItems.length) return <EmptyState icon={<FileText className="h-5 w-5" />} message={t('pages.common.noData')} />;
            return (
            <>
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead sortKey="id" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('pages.deals.table.deal')}</SortableHead>
                  <SortableHead sortKey="client" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('pages.deals.table.client')}</SortableHead>
                  <SortableHead sortKey="stage" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('pages.deals.table.stage')}</SortableHead>
                  <SortableHead sortKey="value" current={listParams.ordering} onChange={listParams.toggleOrdering} className="text-right">{t('pages.deals.table.value')}</SortableHead>
                  <TableHead>{t('pages.deals.table.manager')}</TableHead>
                  <SortableHead sortKey="created_at" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('pages.deals.table.date')}</SortableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((deal) => (
                  <TableRow
                    key={deal.id}
                    className="cursor-pointer"
                    onClick={() => openDeal(deal)}
                  >
                    <TableCell>
                      <span className="font-medium">{deal.title || `#${deal.id}`}</span>
                      {/* Multi-seller routing — show which sellers this RFQ targets. */}
                      {(deal.target_sellers_data?.length ?? 0) > 0 && (
                        <span className="mt-0.5 block text-xs text-muted-foreground">
                          {t('pages.deals.routedTo')}: {deal.target_sellers_data!.map((seller) => seller.name).join(', ')}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {deal.client_name || deal.company_name || ''}
                    </TableCell>
                    <TableCell>
                      <StatusBadge
                        label={deal.stage_name ?? ''}
                        variant={getDealStageVariant(deal.stage_code ?? '')}
                      />
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {deal.total_value ? formatCurrency(Number(deal.total_value)) : <span className="text-muted-foreground">—</span>}
                    </TableCell>
                    <TableCell className="text-sm">
                      {deal.manager_name
                        ? <span>{deal.manager_name}</span>
                        : <span className="text-muted-foreground italic">{t('pages.deals.table.managerUnassigned')}</span>}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      <div className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {new Date(deal.created_at).toLocaleDateString()}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-center" onClick={(e) => e.stopPropagation()}>
                        <Button variant="ghost" size="sm" onClick={() => openDeal(deal)} aria-label={t('pages.deals.detail.openQuote')}>
                          <Eye className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
            </>
            );
          })()}
        </CardContent>
      </Card>
      )}
    </PageShell>
  );
}

export default DealsPage;
