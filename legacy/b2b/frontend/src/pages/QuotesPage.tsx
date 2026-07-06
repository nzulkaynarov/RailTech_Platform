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
  Calculator, FileText, MoreHorizontal, Send, FileDown, ShieldAlert,
} from 'lucide-react';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { ConfirmActionDialog } from '@/components/Admin/ConfirmActionDialog';
import { translateApiError } from '@/lib/apiError';
import { useUserStore } from '@/store/userStore';
import { QuoteStatus, quoteStatusLabelKey } from '@/lib/codes';
import { useCurrencyStore } from '@/store/currencyStore';
import { useQuotes, useSendQuoteToClient, useQuoteStatuses, useForceApproveQuote, useGenerateQuotePDF } from '@/hooks/useCRM';
import { sumMoney } from '@/utils/decimal';
import { crmApi } from '@/api/crmApi';
import type { Quote } from '@/api/crmApi';
import { toast } from 'sonner';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { Toolbar, Pager, useListParams, applyListParams } from '@/components/DataTable';

export function QuotesPage() {
  const { t } = useTranslation();
  const { activeStatus, role } = useUserStore();
  const { data: quotes, isLoading, isError, refetch } = useQuotes();
  const sendToClient = useSendQuoteToClient();
  const generatePDF = useGenerateQuotePDF();
  const forceApproveMut = useForceApproveQuote();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const isBuyer = activeStatus === 'BUYER';
  const isPlatformAdmin = role === 'ADMIN';

  const quotesList = quotes ?? [];
  const { data: statuses } = useQuoteStatuses();
  const listParams = useListParams(['status'] as const, { defaultOrdering: '-created_at' });
  const [forceApproveTarget, setForceApproveTarget] = useState<Quote | null>(null);
  const [forceApproveReason, setForceApproveReason] = useState('');
  // Send-to-client is irreversible + client-visible — confirm before firing.
  // One dialog for the whole list; track which row's КП is being sent.
  const [sendConfirmId, setSendConfirmId] = useState<number | null>(null);

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

  const handleDownloadPDF = async (id: number) => {
    try {
      await crmApi.downloadQuotePDF(id);
    } catch {
      toast.error(t('pages.quotes.toast.actionError'));
    }
  };

  const handleGeneratePDF = async (id: number) => {
    try {
      // ARCH-03: generate enqueues the render (202) — poll the download until the
      // fresh file lands so the click still ends with a saved PDF.
      await generatePDF.mutateAsync(id);
      await crmApi.downloadQuotePDF(id);
      toast.success(t('pages.quotes.toast.pdfGenerated'));
    } catch {
      /* error toast handled globally */
    }
  };

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
          {quoteStatusLabelKey(q.status_code) ? t(quoteStatusLabelKey(q.status_code)) : q.status_name}
        </Badge>
      ),
    },
    {
      id: 'date', sortKey: 'created_at', header: t('pages.quotes.table.date'), className: 'text-muted-foreground',
      cell: (q) => new Date(q.created_at).toLocaleDateString(),
    },
    {
      id: 'actions', header: t('pages.quotes.table.actions'), className: 'text-center', mobileActions: true,
      cell: (q) => (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {!isBuyer && (
              <>
                {/* Only an internally-approved КП can be sent — otherwise the
                    backend FSM rejects it. The actual chain steps live on the
                    КП builder (deal detail). */}
                {q.status_code === QuoteStatus.READY_TO_SEND && (
                  <DropdownMenuItem onClick={() => setSendConfirmId(q.id)}>
                    <Send className="mr-2 h-4 w-4" />
                    {t('pages.quotes.actions.sendToClient')}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => handleGeneratePDF(q.id)}>
                  <FileText className="mr-2 h-4 w-4" />
                  {t('pages.quotes.actions.generatePDF')}
                </DropdownMenuItem>
              </>
            )}
            {/* Buyer accept/reject lives only on the canonical
                request-detail surface (My Requests → open). This
                list stays read-only for the buyer. */}
            <DropdownMenuItem onClick={() => handleDownloadPDF(q.id)}>
              <FileDown className="mr-2 h-4 w-4" />
              {t('pages.quotes.actions.downloadPDF')}
            </DropdownMenuItem>
            {isPlatformAdmin && q.status_code !== QuoteStatus.APPROVED && (
              <DropdownMenuItem
                onClick={() => setForceApproveTarget(q)}
                className="text-warning"
              >
                <ShieldAlert className="mr-2 h-4 w-4" />
                {t('pages.quotes.actions.forceApprove')}
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ];

  return (
    <PageShell
      title={title}
      description={description}
      icon={<Calculator className="h-5 w-5" />}
      stats={stats}
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
            options: (statuses ?? []).map((s) => ({ value: s.code, label: s.name })),
          },
        ]}
      />
      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(quotesList, listParams, {
              searchFields: (q) => [String(q.id), String(q.deal), q.status_name],
              filterPredicates: {
                status: (q, v) => q.status_code === v,
              },
              sortAccessors: {
                id: (q) => q.id,
                amount: (q) => Number(q.total_incl_vat) || 0,
                status: (q) => q.status_name ?? '',
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

      <ConfirmActionDialog
        open={sendConfirmId != null}
        onOpenChange={(o) => { if (!o) setSendConfirmId(null); }}
        title={t('confirmActions.sendQuote.title')}
        description={t('confirmActions.sendQuote.description')}
        variant="primary"
        confirmLabel={t('pages.quotes.actions.sendToClient')}
        onConfirm={async () => {
          if (sendConfirmId == null) return;
          const id = sendConfirmId;
          await sendToClient.mutateAsync(id);
          toast.success(t('pages.quotes.toast.sentSuccess', { id }));
        }}
        translateError={(code) => translateApiError(code)}
      />
    </PageShell>
  );
}

export default QuotesPage;
