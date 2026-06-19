import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
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
import { translateApiError } from '@/lib/apiError';
import { useUserStore } from '@/store/userStore';
import { QuoteStatus } from '@/lib/codes';
import { useCurrencyStore } from '@/store/currencyStore';
import { useQuotes, useSendQuoteToClient, useQuoteStatuses, useForceApproveQuote, useGenerateQuotePDF } from '@/hooks/useCRM';
import { sumMoney } from '@/utils/decimal';
import { crmApi } from '@/api/crmApi';
import type { Quote } from '@/api/crmApi';
import { toast } from 'sonner';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';

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

  const handleSendToClient = async (id: number) => {
    try {
      await sendToClient.mutateAsync(id);
      toast.success(t('pages.quotes.toast.sentSuccess', { id }));
    } catch {
      toast.error(t('pages.quotes.toast.actionError'));
    }
  };

  const handleDownloadPDF = async (id: number) => {
    try {
      await crmApi.downloadQuotePDF(id);
    } catch {
      toast.error(t('pages.quotes.toast.actionError'));
    }
  };

  const handleGeneratePDF = async (id: number) => {
    try {
      await generatePDF.mutateAsync(id);
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
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead sortKey="id" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('pages.quotes.table.number')}</SortableHead>
                  <TableHead>{isBuyer ? t('pages.quotes.table.supplier') : t('pages.quotes.table.client')}</TableHead>
                  <TableHead className="text-center">{t('pages.quotes.table.items')}</TableHead>
                  <SortableHead sortKey="amount" current={listParams.ordering} onChange={listParams.toggleOrdering} className="text-right">{t('pages.quotes.table.amount')}</SortableHead>
                  <SortableHead sortKey="status" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('pages.quotes.table.status')}</SortableHead>
                  <SortableHead sortKey="created_at" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('pages.quotes.table.date')}</SortableHead>
                  <TableHead className="text-center">{t('pages.quotes.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((q: Quote) => (
                  <TableRow key={q.id}>
                    <TableCell className="font-medium">#{q.id}-v{q.version}</TableCell>
                    <TableCell>{t('pages.quotes.dealRef', { id: q.deal })}</TableCell>
                    <TableCell className="text-center tabular-nums">{q.items?.length ?? 0}</TableCell>
                    <TableCell className="text-right tabular-nums font-medium">{formatCurrency(Number(q.total_incl_vat))}</TableCell>
                    <TableCell>
                      <Badge variant={getStatusBadgeVariant(q.status_code)}>
                        {q.status_name}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{new Date(q.created_at).toLocaleDateString()}</TableCell>
                    <TableCell className="text-center">
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
                                <DropdownMenuItem onClick={() => handleSendToClient(q.id)}>
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
    </PageShell>
  );
}

export default QuotesPage;
