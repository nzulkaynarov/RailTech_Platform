import { useState } from 'react'; import { useTranslation } from 'react-i18next'; import { toast } from 'sonner'; import { FileText, Clock, Eye, Handshake, Loader2, Undo2 } from 'lucide-react'; import { Card, CardContent } from '@/components/ui/card'; import { formatDate } from '@/lib/formatLocale'; import { Button } from '@/components/ui/button'; import { StatusBadge } from '@/components/ui/StatusBadge'; import { getDealStageVariant } from '@/lib/statusVariants'; import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable'; import { Toolbar, Pager } from '@/components/DataTable';
import { useListParams, applyListParams } from '@/components/DataTable/listParams';
import { useCurrencyStore } from '@/store/currencyStore';
import { useUserStore } from '@/store/userStore';
import { useDeals, useDealStages, useClaimDeal, useReleaseDeal } from '@/hooks/useCRM';
import { useIsSoloSeller } from '@/hooks/useCapabilities';
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
  // Весь список сделок, а не первые двадцать: 21-я иначе недостижима — ни открыть, ни найти.
  const { data: deals, isLoading, isError, refetch } = useDeals(undefined, { fetchAll: true });
  const { data: stages } = useDealStages();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const activeStatus = useUserStore((s) => s.activeStatus);
  const claimMut = useClaimDeal();
  const releaseMut = useReleaseDeal();
  // Wave B2 (auto-claim): a solo seller has no one to route work between, so «Взять в работу» is
  // noise — hide it. Multi-member companies keep claim (it still routes the queue). UI-only.
  const isSoloSeller = useIsSoloSeller();

  // Second in-funnel path to «взять в работу» (Kanban is the first). Claim is a
  // seller-only pull from the routed queue — hidden in the BUYER context and for
  // already-owned deals. Ownership keys off `assigned_to` (the id), which the deal
  // serializer derives from the VIEWER's OWN DealSellerRouting row, so null == this
  // seller's copy is unclaimed. Reuses useClaimDeal + the `dealsKanban.claim` key.
  // Localize the deal-stage label (codes.ts convention: render t(DEAL_STAGE_LABEL_KEY[code])
  // instead of the RU-only backend stage_name), falling back to stage_name for unknown codes.
  const stageLabel = (code: string | undefined, fallback: string | undefined) =>
    code && DEAL_STAGE_LABEL_KEY[code] ? t(DEAL_STAGE_LABEL_KEY[code]) : (fallback ?? '');

  const canClaim = (deal: Deal) => activeStatus === 'SELLER' && deal.assigned_to == null && !isSoloSeller;
  const handleClaim = (dealId: number) => {
    claimMut.mutate(dealId, {
      onSuccess: () => toast.success(t('dealsKanban.claimed')),
      onError: (err) => toast.error(translateApiError(err)),
    });
  };
  const handleRelease = (dealId: number) => {
    releaseMut.mutate(dealId, {
      onSuccess: () => toast.success(t('dealsKanban.released')),
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
      // Ресерч 2026-07-28: колонка читала legacy deal.manager_name, которого в list-ответе
      // ВООБЩЕ нет — всегда «Не назначен», даже когда заявка взята. Владение живёт на
      // routing.assigned_to (как в Канбане) — показываем его.
      id: 'manager', header: t('pages.deals.table.responsible'),
      cell: (deal) => (deal.assigned_to != null
        ? <span>{deal.assigned_to_name || t('dealsKanban.assigned')}</span>
        : <span className="text-muted-foreground italic">{t('pages.deals.table.managerUnassigned')}</span>),
    },
    {
      id: 'date', sortKey: 'created_at', header: t('pages.deals.table.date'), className: 'text-muted-foreground text-xs',
      cell: (deal) => (
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {formatDate(deal.created_at)}
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
          {/* Обратное действие: запись уходит обратно в очередь команды. Право считает сервер
              (`viewer_can_release`) тем же предикатом, что и сам возврат. */}
          {deal.viewer_can_release ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1 text-xs"
              disabled={releaseMut.isPending}
              onClick={() => handleRelease(deal.id)}
            >
              {releaseMut.isPending && releaseMut.variables === deal.id ? (
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
              ) : (
                <Undo2 className="h-3 w-3" aria-hidden="true" />
              )}
              {t('dealsKanban.release')}
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

      {/* Табличный вид проверял загрузку и ошибку, а канбан — нет: при недоступном API он
          рисовал пустые колонки без объяснения и без «Повторить» (аудит UI, U2). Оба вида
          отвечают на одно и то же состояние. */}
      {view === 'kanban' ? (
        isLoading ? (
          <LoadingRows rows={5} />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : (
          <DealsKanban
            deals={deals ?? []}
            stages={stages}
            onOpen={openDeal}
          />
        )
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
