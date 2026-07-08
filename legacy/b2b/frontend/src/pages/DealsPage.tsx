import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { FileText, Clock, Eye, Handshake, Loader2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { StatusBadge, getDealStageVariant } from '@/components/ui/StatusBadge';
import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable';
import { Toolbar, Pager, useListParams, applyListParams } from '@/components/DataTable';
import { useCurrencyStore } from '@/store/currencyStore';
import { useUserStore } from '@/store/userStore';
import { useDeals, useDealStages, useClaimDeal } from '@/hooks/useCRM';
import { DEAL_STAGE_LABEL_KEY } from '@/lib/codes';
import { translateApiError } from '@/lib/apiError';
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
  const claimMut = useClaimDeal();

  // Second in-funnel path to «взять в работу» (Kanban is the first). Claim is a
  // seller-only pull from the routed queue — hidden in the BUYER context and for
  // already-owned deals. Ownership keys off `assigned_to` (the id), which the deal
  // serializer derives from the VIEWER's OWN DealSellerRouting row, so null == this
  // seller's copy is unclaimed. Reuses useClaimDeal + the `dealsKanban.claim` key.
  // Localize the deal-stage label (codes.ts convention: render t(DEAL_STAGE_LABEL_KEY[code])
  // instead of the RU-only backend stage_name), falling back to stage_name for unknown codes.
  const stageLabel = (code: string | undefined, fallback: string | undefined) =>
    code && DEAL_STAGE_LABEL_KEY[code] ? t(DEAL_STAGE_LABEL_KEY[code]) : (fallback ?? '');

  const canClaim = (deal: Deal) => activeStatus === 'SELLER' && deal.assigned_to == null;
  const handleClaim = (dealId: number) => {
    claimMut.mutate(dealId, {
      onSuccess: () => toast.success(t('dealsKanban.claimed')),
      onError: (err) => toast.error(translateApiError(err)),
    });
  };

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

  const columns: ResponsiveColumn<Deal>[] = [
    {
      id: 'deal', sortKey: 'id', header: t('pages.deals.table.deal'), mobileTitle: true,
      cell: (deal) => (
        <>
          <span className="font-medium">{deal.title || `#${deal.id}`}</span>
          {/* Multi-seller routing — show which sellers this RFQ targets. */}
          {(deal.target_sellers_data?.length ?? 0) > 0 && (
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {t('pages.deals.routedTo')}: {deal.target_sellers_data!.map((seller) => seller.name).join(', ')}
            </span>
          )}
        </>
      ),
    },
    {
      id: 'client', sortKey: 'client', header: t('pages.deals.table.client'),
      cell: (deal) => <span className="text-muted-foreground">{deal.client_name || deal.company_name || ''}</span>,
    },
    {
      id: 'stage', sortKey: 'stage', header: t('pages.deals.table.stage'),
      cell: (deal) => <StatusBadge label={stageLabel(deal.stage_code, deal.stage_name)} variant={getDealStageVariant(deal.stage_code ?? '')} />,
    },
    {
      id: 'value', sortKey: 'value', header: t('pages.deals.table.value'), className: 'text-right',
      cell: (deal) => (
        <span className="font-medium tabular-nums">
          {deal.total_value ? formatCurrency(Number(deal.total_value)) : <span className="text-muted-foreground">—</span>}
        </span>
      ),
    },
    {
      id: 'manager', header: t('pages.deals.table.manager'),
      cell: (deal) => (deal.manager_name
        ? <span>{deal.manager_name}</span>
        : <span className="text-muted-foreground italic">{t('pages.deals.table.managerUnassigned')}</span>),
    },
    {
      id: 'date', sortKey: 'created_at', header: t('pages.deals.table.date'), className: 'text-muted-foreground text-xs',
      cell: (deal) => (
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {new Date(deal.created_at).toLocaleDateString()}
        </span>
      ),
    },
    {
      id: 'open', header: '', className: 'text-right', mobileHidden: true,
      cell: (deal) => (
        <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
          {canClaim(deal) ? (
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1 text-xs"
              disabled={claimMut.isPending}
              onClick={() => handleClaim(deal.id)}
            >
              {claimMut.isPending && claimMut.variables === deal.id ? (
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
              ) : (
                <Handshake className="h-3 w-3" aria-hidden="true" />
              )}
              {t('dealsKanban.claim')}
            </Button>
          ) : null}
          <Button variant="ghost" size="sm" onClick={() => openDeal(deal)} aria-label={t('pages.deals.detail.openQuote')}>
            <Eye className="h-3.5 w-3.5" />
          </Button>
        </div>
      ),
    },
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
            options: (stages ?? []).map((s) => ({ value: s.code, label: stageLabel(s.code, s.name) })),
          },
        ]}
        newLabel={activeStatus === 'BUYER' ? t('createDeal.title') : undefined}
        onNew={activeStatus === 'BUYER' ? () => setCreateOpen(true) : undefined}
        extra={
          <div className="inline-flex shrink-0 rounded-md border p-0.5 text-xs">
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
            <ResponsiveDataTable
              columns={columns}
              rows={pageItems}
              getRowId={(deal) => deal.id}
              onRowClick={openDeal}
              sorting={{ ordering: listParams.ordering, onToggle: listParams.toggleOrdering }}
            />
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
