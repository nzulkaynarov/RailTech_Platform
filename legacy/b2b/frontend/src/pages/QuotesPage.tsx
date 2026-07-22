import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Calculator, MoreHorizontal, Send, ShieldAlert,
} from 'lucide-react';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { NewQuoteDialog } from '@/components/CRM/NewQuoteDialog';
import { SendQuoteDialog } from '@/components/CRM/SendQuoteDialog';
import { translateApiError } from '@/lib/apiError';
import { useUserStore } from '@/store/userStore';
import { QuoteStatus, quoteStatusLabelKey } from '@/lib/codes';
import { publicQuoteUrl } from '@/lib/quoteSend';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { useCurrencyStore } from '@/store/currencyStore';
import { useQuotes, useQuote, useDeal, useQuoteStatuses, useForceApproveQuote } from '@/hooks/useCRM';
import { sumMoney } from '@/utils/decimal';
import type { Quote } from '@/api/crmApi';
import { toast } from 'sonner';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { Toolbar, Pager, useListParams, applyListParams } from '@/components/DataTable';

export function QuotesPage() {
  const { t } = useTranslation();
  const { activeStatus, role } = useUserStore();
  const { data: quotes, isLoading, isError, refetch } = useQuotes();
  const forceApproveMut = useForceApproveQuote();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const isBuyer = activeStatus === 'BUYER';
  const isPlatformAdmin = role === 'ADMIN';

  const quotesList = quotes ?? [];
  const { data: statuses } = useQuoteStatuses();
  const listParams = useListParams(['status'] as const, { defaultOrdering: '-created_at' });
  const [forceApproveTarget, setForceApproveTarget] = useState<Quote | null>(null);
  const [forceApproveReason, setForceApproveReason] = useState('');
  // Unified send (wave B2): the registry opens the SAME composer the builder uses —
  // recipient · validity · margin-vs-floor · approval outcome · below-floor justification —
  // so the seller gets ONE send experience from any surface. Track which row's КП is sending.
  const [sendConfirmId, setSendConfirmId] = useState<number | null>(null);
  // Wave E F2 — the seller-side «Новый КП» entry (offer-first, no buyer заявка needed).
  const [newQuoteOpen, setNewQuoteOpen] = useState(false);
  const sendTargetQuote = quotesList.find((q) => q.id === sendConfirmId);
  // The composer needs the Deal (recipient/context) AND the quote DETAIL: the list serializer
  // deliberately omits economics + approval_steps (N+1 guard), so feeding it the list row would
  // show «Маржа скрыта» to a cost-visible seller and mislabel a real approved chain as
  // «согласовано автоматически». Both fetches run lazily, only while the dialog is open.
  const { data: sendDeal } = useDeal(sendTargetQuote?.deal ?? 0);
  const { data: sendQuoteDetail } = useQuote(sendConfirmId ?? 0);

  const title = isBuyer ? t('pages.quotes.buyerTitle') : t('pages.quotes.sellerTitle');
  const description = isBuyer ? t('pages.quotes.buyerDescription') : t('pages.quotes.sellerDescription');
  const stats = isBuyer
    ? [
        { label: t('pages.quotes.stats.total'), value: String(quotesList.length) },
        { label: t('pages.quotes.stats.underReview'), value: String(quotesList.filter(q => q.status_code === 'SENT').length) },
        { label: t('pages.quotes.stats.accepted'), value: String(quotesList.filter(q => q.status_code === 'APPROVED').length) },
        { label: t('pages.quotes.stats.totalAmount'), value: formatCurrency(sumMoney(quotesList.map(q => q.total_incl_vat))) },
      ]
    : [
        { label: t('pages.quotes.stats.drafts'), value: String(quotesList.filter(q => q.status_code === 'DRAFT').length) },
        { label: t('pages.quotes.stats.sent'), value: String(quotesList.filter(q => q.status_code === 'SENT').length) },
        { label: t('pages.quotes.stats.approved'), value: String(quotesList.filter(q => q.status_code === 'APPROVED').length) },
        { label: t('pages.quotes.stats.pipeline'), value: String(quotesList.filter(q => !['APPROVED', 'REJECTED', 'EXPIRED'].includes(q.status_code)).length) },
      ];

  const handleForceApprove = async () => {
    if (!forceApproveTarget) return;
    if (!forceApproveReason.trim()) {
      toast.error(t('pages.quotes.toast.forceReasonRequired'));
      return;
    }
    try {
      await forceApproveMut.mutateAsync({ id: forceApproveTarget.id, reason: forceApproveReason });
      toast.success(t('pages.quotes.toast.forceApproved', { id: forceApproveTarget.id }));
      setForceApproveTarget(null);
      setForceApproveReason('');
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
      cell: (q) => <span className="font-medium">#{q.id}-v{q.version}</span>,
    },
    {
      id: 'party', header: isBuyer ? t('pages.quotes.table.supplier') : t('pages.quotes.table.client'),
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
      cell: (q) => new Date(q.created_at).toLocaleDateString(),
    },
    {
      // Unified document actions (Просмотр/Печать/Скачать/Копировать ссылку) + the status-gated
      // Send/force menu. `data-row-action` keeps a click here from also opening the row.
      id: 'actions', header: t('pages.quotes.table.actions'), className: 'text-center', mobileActions: true,
      cell: (q) => {
        const showStatusMenu = !isBuyer
          && (q.status_code === QuoteStatus.READY_TO_SEND
            || (isPlatformAdmin && q.status_code !== QuoteStatus.APPROVED));
        return (
        <div className="flex items-center justify-center gap-1" data-row-action>
          <DocumentActions
            request={() => ({ path: `crm/quotes/${q.id}/download-pdf/` })}
            filenameBase={`RailTech_Quote_${q.id}`}
            publicLink={q.public_access_token && !q.public_token_revoked
              ? (publicQuoteUrl(q.public_access_token, window.location.origin) ?? undefined)
              : undefined}
            iconOnly
          />
          {showStatusMenu && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="h-8 w-8 p-0" aria-label={t('pages.quotes.table.actions')}>
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {/* Only an internally-approved КП can be sent — the FSM rejects otherwise. */}
                {q.status_code === QuoteStatus.READY_TO_SEND && (
                  <DropdownMenuItem onClick={() => setSendConfirmId(q.id)}>
                    <Send className="mr-2 h-4 w-4" />
                    {t('pages.quotes.actions.sendToClient')}
                  </DropdownMenuItem>
                )}
                {isPlatformAdmin && q.status_code !== QuoteStatus.APPROVED && (
                  <DropdownMenuItem onClick={() => setForceApproveTarget(q)} className="text-warning">
                    <ShieldAlert className="mr-2 h-4 w-4" />
                    {t('pages.quotes.actions.forceApprove')}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
        );
      },
    },
  ];

  return (
    <PageShell
      title={title}
      description={description}
      icon={<Calculator className="h-5 w-5" />}
      stats={stats}
      actions={
        isBuyer
          ? undefined
          : [{ label: t('newQuote.action'), onClick: () => setNewQuoteOpen(true) }]
      }
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
              // Click a row to OPEN the КП: the seller lands on the builder, the buyer on their
              // canonical request surface (both keyed by the deal).
              onRowClick={(q) => { window.location.hash = isBuyer ? `request-detail/${q.deal}` : `deal-quote/${q.deal}`; }}
              sorting={{ ordering: listParams.ordering, onToggle: listParams.toggleOrdering }}
            />
            <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
            </>
            );
          })()}
        </CardContent>
      </Card>
      <AlertDialog
        open={!!forceApproveTarget}
        onOpenChange={(o) => { if (!o) { setForceApproveTarget(null); setForceApproveReason(''); } }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2 text-warning">
              <ShieldAlert className="h-4 w-4" />
              {t('pages.quotes.confirmForceApprove')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('pages.quotes.forceApproveHint', { id: forceApproveTarget?.id })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <Label htmlFor="forceApproveReason">{t('pages.quotes.forceApproveReason')}</Label>
            <Textarea
              id="forceApproveReason"
              value={forceApproveReason}
              onChange={(e) => setForceApproveReason(e.target.value)}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleForceApprove} disabled={forceApproveMut.isPending}>
              {t('pages.quotes.actions.forceApprove')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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
