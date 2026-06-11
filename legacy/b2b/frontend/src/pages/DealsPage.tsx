import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, Clock, Eye, Gavel, FileSignature } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet';
import { Separator } from '@/components/ui/separator';
import { StatusBadge, getDealStageVariant } from '@/components/ui/StatusBadge';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';
import { useCurrencyStore } from '@/store/currencyStore';
import { useUserStore } from '@/store/userStore';
import { useDeals, useDealStages, useChangeDealStage } from '@/hooks/useCRM';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import { OpenRfqDialog } from '@/components/CRM/OpenRfqDialog';
import { CreateDealDialog } from '@/components/CRM/CreateDealDialog';
import { GenerateQuoteDialog } from '@/components/CRM/GenerateQuoteDialog';
import { DealsKanban } from '@/components/CRM/DealsKanban';
import { GenerateContractDialog } from '@/components/CRM/GenerateContractDialog';
import { QuoteBuilderGrid } from '@/components/Admin/QuoteBuilderGrid';
import { QuoteApprovalChain } from '@/components/CRM/QuoteApprovalChain';
import { DealStage, QuoteStatus } from '@/lib/codes';
import type { Deal } from '@/api/crmApi';

/* ─── Detail Sheet ─────────────────────────────────────────────────── */

function DealDetailSheet({
  deal,
  open,
  onOpenChange,
}: {
  deal: Deal | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const activeStatus = useUserStore((s) => s.activeStatus);
  const [rfqOpen, setRfqOpen] = useState(false);
  const [quoteOpen, setQuoteOpen] = useState(false);
  const [contractOpen, setContractOpen] = useState(false);
  const changeStage = useChangeDealStage();
  if (!deal) return null;

  // Role split: opening the RFQ/заявка is a BUYER action; building the КП and
  // generating the contract are SELLER actions. The backend enforces this too;
  // gating here stops the wrong-role buttons from rendering (e.g. a buyer must
  // never see "Создать КП").
  const isBuyer = activeStatus === 'BUYER';
  const isSeller = !isBuyer; // SELLER / MANUFACTURER context (store filters by can_sell)
  const stageCode = deal.stage_code ?? '';
  const quoteStatus = deal.active_quote?.status_code ?? '';
  const canOpenRfq = isBuyer && ([DealStage.DRAFT, DealStage.KYC_PENDING] as string[]).includes(stageCode);
  // Seller "take into work": a fresh заявка lands in DRAFT; the seller advances it
  // to SOURCING so the КП builder ("Создать КП") becomes available.
  const canTakeIntoWork = isSeller
    && !deal.active_quote
    && ([DealStage.DRAFT, DealStage.KYC_PENDING, DealStage.RFQ_OPEN] as string[]).includes(stageCode);
  const canBuildQuote = isSeller
    && ([DealStage.SOURCING, DealStage.CALCULATING] as string[]).includes(stageCode)
    && !deal.active_quote;
  // The seller works the КП inline (builder + approval chain) whenever the deal has one.
  const showQuoteWorkspace = isSeller && !!deal.active_quote;
  const approvedQuote = isSeller && deal.active_quote
    && ([QuoteStatus.APPROVED, QuoteStatus.SENT] as string[]).includes(quoteStatus);

  const rows = [
    { label: t('pages.deals.detail.client'), value: deal.client_name || deal.company_name },
    { label: t('pages.deals.detail.manager'), value: deal.manager_name },
    { label: t('pages.deals.detail.stage'), value: deal.stage_name },
    { label: t('pages.deals.detail.totalValue'), value: deal.total_value ? formatCurrency(Number(deal.total_value)) : undefined },
    { label: t('pages.deals.detail.created'), value: new Date(deal.created_at).toLocaleDateString() },
    ...(deal.updated_at ? [{ label: t('pages.deals.detail.updated'), value: new Date(deal.updated_at).toLocaleDateString() }] : []),
  ].filter(r => r.value);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className={`overflow-y-auto ${showQuoteWorkspace ? 'sm:max-w-4xl' : 'sm:max-w-lg'}`}>
        <SheetHeader>
          <SheetTitle>{deal.title || `${t('pages.deals.deal')} #${deal.id}`}</SheetTitle>
          <SheetDescription>
            {deal.client_name || deal.company_name || `D-${deal.id}`}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-2 space-y-6 px-4">
          <section className="space-y-3">
            <h3 className="text-sm font-semibold">{t('pages.deals.detail.info')}</h3>
            {rows.map((r) => (
              <div key={r.label} className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">{r.label}</span>
                <span className="text-sm font-medium">{r.value}</span>
              </div>
            ))}
          </section>

          <Separator />

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('pages.deals.detail.stage')}</h3>
            <StatusBadge label={deal.stage_name ?? ''} variant={getDealStageVariant(deal.stage_code ?? '')} />
          </section>

          {deal.notes && (
            <>
              <Separator />
              <section className="space-y-2">
                <h3 className="text-sm font-semibold">{t('pages.deals.detail.notes')}</h3>
                <div className="rounded-lg border bg-muted/50 p-3">
                  <p className="text-sm whitespace-pre-wrap">{deal.notes}</p>
                </div>
              </section>
            </>
          )}

          <Separator />
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t('pages.deals.detail.actions')}</h3>
            <div className="flex flex-wrap gap-2">
              {canOpenRfq && (
                <Button size="sm" variant="outline" onClick={() => setRfqOpen(true)}>
                  <Gavel className="mr-2 h-4 w-4" />
                  {t('rfqDialog.open')}
                </Button>
              )}
              {canTakeIntoWork && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={changeStage.isPending}
                  onClick={() => changeStage.mutate({ id: deal.id, stage: DealStage.SOURCING })}
                >
                  <FileText className="mr-2 h-4 w-4" />
                  {t('pages.deals.detail.takeIntoWork')}
                </Button>
              )}
              {canBuildQuote && (
                <Button size="sm" onClick={() => setQuoteOpen(true)}>
                  <FileText className="mr-2 h-4 w-4" />
                  {t('generateQuote.submit')}
                </Button>
              )}
              {approvedQuote && (
                <Button size="sm" onClick={() => setContractOpen(true)}>
                  <FileSignature className="mr-2 h-4 w-4" />
                  {t('contractGenerateDialog.generate')}
                </Button>
              )}
            </div>
          </section>

          {/* Seller КП workspace — the approval chain + the line-item/price builder,
              shown inline once the deal has a КП. This is where the seller actually
              fills positions, sets margin, and runs документооборот. */}
          {showQuoteWorkspace && deal.active_quote && (
            <>
              <Separator />
              <section className="space-y-3">
                <h3 className="text-sm font-semibold">{t('quote.title')}</h3>
                <QuoteApprovalChain quote={deal.active_quote} />
                <div className="h-[460px]">
                  <QuoteBuilderGrid dealId={deal.id} />
                </div>
              </section>
            </>
          )}
        </div>

        <OpenRfqDialog
          dealId={deal.id}
          open={rfqOpen}
          onOpenChange={setRfqOpen}
        />
        <GenerateQuoteDialog
          dealId={deal.id}
          open={quoteOpen}
          onOpenChange={setQuoteOpen}
        />
        <GenerateContractDialog
          quoteId={deal.active_quote?.id ?? null}
          open={contractOpen}
          onOpenChange={setContractOpen}
        />
      </SheetContent>
    </Sheet>
  );
}

/* ─── Main Page ────────────────────────────────────────────────────── */

export function DealsPage() {
  const { t } = useTranslation();
  const { data: deals, isLoading } = useDeals();
  const { data: stages } = useDealStages();
  const formatCurrency = useCurrencyStore((s) => s.format);

  const listParams = useListParams(['stage'] as const, { defaultOrdering: '-created_at' });
  const [detailTarget, setDetailTarget] = useState<Deal | null>(null);
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

  const selectedDeal = useMemo(() => {
    if (!detailTarget || !deals) return null;
    return deals.find((d) => d.id === detailTarget.id) ?? detailTarget;
  }, [deals, detailTarget]);

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
        newLabel={t('createDeal.title')}
        onNew={() => setCreateOpen(true)}
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
          onOpen={(d) => setDetailTarget(d)}
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
                    onClick={() => setDetailTarget(deal)}
                  >
                    <TableCell>
                      <span className="font-medium">{deal.title || `#${deal.id}`}</span>
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
                        <Button variant="ghost" size="sm" onClick={() => setDetailTarget(deal)}>
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

      <DealDetailSheet
        deal={selectedDeal}
        open={!!detailTarget}
        onOpenChange={(open) => { if (!open) setDetailTarget(null); }}
      />
    </PageShell>
  );
}

export default DealsPage;
