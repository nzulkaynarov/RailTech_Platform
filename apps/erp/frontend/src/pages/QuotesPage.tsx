import { useState } from 'react'; import { useTranslation } from 'react-i18next'; import { Card, CardContent } from '@/components/ui/card'; import { formatDate } from '@/lib/formatLocale'; import { Badge } from '@/components/ui/badge'; import { Button } from '@/components/ui/button'; import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable'; import {   DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, } from '@/components/ui/dropdown-menu'; import {   Calculator, Files, MoreHorizontal, Send, } from 'lucide-react'; import { NewQuoteDialog } from '@/components/CRM/NewQuoteDialog'; import { SendQuoteDialog } from '@/components/CRM/SendQuoteDialog'; import { translateApiError } from '@/lib/apiError'; import { QuoteStatus, quoteStatusLabelKey } from '@/lib/codes'; import { publicQuoteUrl } from '@/lib/quoteSend'; import { DocumentActions } from '@/components/Shared/DocumentActions'; import { useCurrencyStore } from '@/store/currencyStore'; import { useQuotes, useQuote, useDeal, useQuoteStatuses, useDuplicateQuote } from '@/hooks/useCRM'; import type { Quote } from '@/api/crmApi'; import { toast } from 'sonner'; import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell'; import { Toolbar, Pager } from '@/components/DataTable';
import { useListParams, applyListParams } from '@/components/DataTable/listParams';

export function QuotesPage() {
  const { t } = useTranslation();
  const { data: quotes, isLoading, isError, refetch } = useQuotes();
  const duplicateMut = useDuplicateQuote();
  const formatCurrency = useCurrencyStore((s) => s.format);

  const quotesList = quotes ?? [];
  const { data: statuses } = useQuoteStatuses();
  const listParams = useListParams(['status'] as const, { urlKey: 'quotes', defaultOrdering: '-created_at' });
  // Unified send (wave B2): the registry opens the SAME composer the builder uses —
  // recipient · validity · margin-vs-floor · approval outcome · below-floor justification —
  // so the seller gets ONE send experience from any surface. Track which row's КП is sending.
  const [sendConfirmId, setSendConfirmId] = useState<number | null>(null);
  // Wave E F2 — «Новый КП» from the registry (offer-first, no client заявка needed).
  const [newQuoteOpen, setNewQuoteOpen] = useState(false);
  const sendTargetQuote = quotesList.find((q) => q.id === sendConfirmId);
  // The composer needs the Deal (recipient/context) AND the quote DETAIL: the list serializer
  // deliberately omits economics + approval_steps (N+1 guard), so feeding it the list row would
  // show «Маржа скрыта» to a cost-visible seller and mislabel a real approved chain as
  // «согласовано автоматически». Both fetches run lazily, only while the dialog is open.
  const { data: sendDeal } = useDeal(sendTargetQuote?.deal ?? 0);
  const { data: sendQuoteDetail } = useQuote(sendConfirmId ?? 0);

  const title = t('pages.quotes.sellerTitle');
  const description = t('pages.quotes.sellerDescription');
  const stats = [
    { label: t('pages.quotes.stats.drafts'), value: String(quotesList.filter(q => q.status_code === 'DRAFT').length) },
    { label: t('pages.quotes.stats.sent'), value: String(quotesList.filter(q => q.status_code === 'SENT').length) },
    { label: t('pages.quotes.stats.approved'), value: String(quotesList.filter(q => q.status_code === 'APPROVED').length) },
    { label: t('pages.quotes.stats.pipeline'), value: String(quotesList.filter(q => !['APPROVED', 'REJECTED', 'EXPIRED'].includes(q.status_code)).length) },
  ];

  // WP-G1 — «Дублировать КП» from the registry: deep-copy → land the seller in the new draft's
  // builder. Degrades to an error toast if the backend duplicate endpoint isn't present yet.
  const handleDuplicate = async (quote: Quote) => {
    try {
      const newQuote = await duplicateMut.mutateAsync(quote.id);
      toast.success(t('pages.quotes.toast.duplicated', { id: quote.id }));
      window.location.hash = `deal-quote/${newQuote.deal}`;
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  /**
   * Localized display label for a КП status. Resolves by CODE; the RU-only DB
   * `status_name` is a deliberate fallback for a code this build's map does not
   * know yet (backend seeded a new status ahead of the frontend). For every seeded
   * code the map hits, so a Russian label in an EN UI means the map is stale.
   */
  const statusLabel = (quote: { status_code: string; status_name?: string | null }): string =>
    quoteStatusLabelKey(quote.status_code)
      ? t(quoteStatusLabelKey(quote.status_code))
      : (quote.status_name ?? quote.status_code);

  /** Compare by status code, not by translated name (Iron Rule #2) */
  const getStatusBadgeVariant = (statusCode: string): 'default' | 'secondary' | 'destructive' | 'outline' => {
    switch (statusCode) {
      case 'APPROVED': return 'default';
      case 'SENT': return 'secondary';
      case 'REJECTED': return 'destructive';
      case 'EXPIRED': return 'destructive';
      default: return 'outline'; // DRAFT and unknown
    }
  };

  const columns: ResponsiveColumn<Quote>[] = [
    {
      id: 'number', sortKey: 'id', header: t('pages.quotes.table.number'), mobileTitle: true,
      // Документный номер КП (КП-2026-00013), а не технический «#13-v1»: так его видит и клиент (D-12).
      cell: (q) => <span className="font-medium">{q.number || `#${q.id}-v${q.version}`}</span>,
    },
    {
      id: 'party', header: t('pages.quotes.table.client'),
      cell: (q) => t('pages.quotes.dealRef', { id: q.deal }),
    },
    {
      id: 'items', header: t('pages.quotes.table.items'), className: 'text-center',
      cell: (q) => <span className="tabular-nums">{q.items?.length ?? 0}</span>,
    },
    {
      id: 'amount', sortKey: 'amount', header: t('pages.quotes.table.amount'), className: 'text-right',
      cell: (q) => <span className="tabular-nums font-medium">{formatCurrency(Number(q.total_incl_vat))}</span>,
    },
    {
      id: 'status', sortKey: 'status', header: t('pages.quotes.table.status'),
      cell: (q) => (
        <Badge variant={getStatusBadgeVariant(q.status_code)}>
          {statusLabel(q)}
        </Badge>
      ),
    },
    {
      id: 'date', sortKey: 'created_at', header: t('pages.quotes.table.date'), className: 'text-muted-foreground',
      cell: (q) => formatDate(q.created_at),
    },
    {
      // Unified document actions (Просмотр/Печать/Скачать/Копировать ссылку) + the status-gated
      // Send/force menu. `data-row-action` keeps a click here from also opening the row.
      id: 'actions', header: t('pages.quotes.table.actions'), className: 'text-center', mobileActions: true,
      // «Дублировать» — действие бэк-офиса, доступно на каждой строке; «Отправить» — только
      // внутренне согласованному КП (FSM отклонит иначе).
      cell: (q) => (
        <div className="flex items-center justify-center gap-1" data-row-action>
          <DocumentActions
            request={() => ({ path: `crm/quotes/${q.id}/download-pdf/` })}
            filenameBase={`Quote_${q.id}`}
            publicLink={q.public_access_token && !q.public_token_revoked
              ? (publicQuoteUrl(q.public_access_token, window.location.origin) ?? undefined)
              : undefined}
            iconOnly
          />
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="h-8 w-8 p-0" aria-label={t('pages.quotes.table.actions')}>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {q.status_code === QuoteStatus.READY_TO_SEND && (
                <DropdownMenuItem onClick={() => setSendConfirmId(q.id)}>
                  <Send className="mr-2 h-4 w-4" />
                  {t('pages.quotes.actions.sendToClient')}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onClick={() => handleDuplicate(q)} disabled={duplicateMut.isPending}>
                <Files className="mr-2 h-4 w-4" />
                {t('pages.quotes.actions.duplicate')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ),
    },
  ];

  return (
    <PageShell
      title={title}
      description={description}
      icon={<Calculator className="h-5 w-5" />}
      stats={stats}
      statsError={isError}
      actions={[{ label: t('newQuote.action'), onClick: () => setNewQuoteOpen(true) }]}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('pages.quotes.searchPlaceholder')}
        filters={[
          {
            key: 'status',
            value: listParams.filters.status,
            onChange: (v) => listParams.setFilter('status', v),
            allLabel: t('pages.quotes.allStatuses'),
            options: (statuses ?? []).map((s) => ({
              value: s.code,
              // Localize by CODE; the RU-only DB `name` is a fallback for codes this
              // build does not know yet, never for the seeded statuses.
              label: quoteStatusLabelKey(s.code) ? t(quoteStatusLabelKey(s.code)) : s.name,
            })),
          },
        ]}
      />
      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(quotesList, listParams, {
              // Search and sort on the LOCALIZED status label so both match what the
              // user actually sees (an EN user typing "sent" must not have to guess
              // the RU DB name). Raw `status_name` stays only as the unknown-code fallback.
              searchFields: (q) => [String(q.id), String(q.deal), statusLabel(q)],
              filterPredicates: {
                status: (q, v) => q.status_code === v,
              },
              sortAccessors: {
                id: (q) => q.id,
                amount: (q) => Number(q.total_incl_vat) || 0,
                status: (q) => statusLabel(q),
                created_at: (q) => q.created_at ?? '',
              },
            });
            if (isLoading) return <LoadingRows rows={5} />;
            if (isError) return <ErrorState onRetry={refetch} />;
            if (!pageItems.length) return <EmptyState icon={<Calculator className="h-5 w-5" />} message={t('pages.common.noData')} />;
            return (
            <>
            <ResponsiveDataTable
              columns={columns}
              rows={pageItems}
              getRowId={(q) => q.id}
              // Click a row to OPEN the КП in the builder (keyed by the deal).
              onRowClick={(q) => { window.location.hash = `deal-quote/${q.deal}`; }}
              sorting={{ ordering: listParams.ordering, onToggle: listParams.toggleOrdering }}
            />
            <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
            </>
            );
          })()}
        </CardContent>
      </Card>
      {/* Unified send composer (wave B2) — the same dialog the КП builder opens, so sending
          from the registry and from the builder is ONE experience (recipient, validity,
          margin-vs-floor, «согласовано автоматически», below-floor justification). Rendered
          only once the target's Deal has loaded. */}
      {sendTargetQuote && sendDeal && sendQuoteDetail && (
        <SendQuoteDialog
          deal={sendDeal}
          quote={sendQuoteDetail}
          open={sendConfirmId != null}
          onOpenChange={(o) => { if (!o) setSendConfirmId(null); }}
          onSent={() => {
            toast.success(t('pages.quotes.toast.sentSuccess', { id: sendTargetQuote.id }));
            setSendConfirmId(null);
          }}
        />
      )}
      <NewQuoteDialog
        open={newQuoteOpen}
        onOpenChange={setNewQuoteOpen}
        onCreated={(dealId) => { window.location.hash = `deal-quote/${dealId}`; }}
      />
    </PageShell>
  );
}

export default QuotesPage;
