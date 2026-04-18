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
  Calculator, FileText, MoreHorizontal, Send, ThumbsUp, ThumbsDown, FileDown,
} from 'lucide-react';
import { useUserStore } from '@/store/userStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { useQuotes, useSendQuoteToClient, useApproveQuote, useQuoteStatuses } from '@/hooks/useCRM';
import { crmApi } from '@/api/crmApi';
import type { Quote } from '@/api/crmApi';
import { toast } from 'sonner';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';
import { CreateQuoteDialog } from '@/components/CRM/CreateQuoteDialog';

export function QuotesPage() {
  const { t } = useTranslation();
  const { activeStatus } = useUserStore();
  const { data: quotes, isLoading } = useQuotes();
  const sendToClient = useSendQuoteToClient();
  const approveQuote = useApproveQuote();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const isBuyer = activeStatus === 'BUYER';

  const quotesList = quotes ?? [];
  const { data: statuses } = useQuoteStatuses();
  const listParams = useListParams(['status'] as const, { defaultOrdering: '-created_at' });
  const [createOpen, setCreateOpen] = useState(false);

  const title = isBuyer ? t('pages.quotes.buyerTitle') : t('pages.quotes.sellerTitle');
  const description = isBuyer ? t('pages.quotes.buyerDescription') : t('pages.quotes.sellerDescription');
  const stats = isBuyer
    ? [
        { label: t('pages.quotes.stats.total'), value: String(quotesList.length) },
        { label: t('pages.quotes.stats.underReview'), value: String(quotesList.filter(q => q.status_code === 'SENT').length) },
        { label: t('pages.quotes.stats.accepted'), value: String(quotesList.filter(q => q.status_code === 'APPROVED').length) },
        { label: t('pages.quotes.stats.totalAmount'), value: String(quotesList.length) },
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

  const handleApprove = async (id: number) => {
    try {
      await approveQuote.mutateAsync(id);
      toast.success(t('pages.quotes.toast.approvedSuccess', { id }));
    } catch {
      toast.error(t('pages.quotes.toast.actionError'));
    }
  };

  const handleReject = async (id: number) => {
    try {
      await crmApi.rejectQuote(id);
      toast.success(t('pages.quotes.toast.rejectedSuccess', { id }));
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
      await crmApi.generateQuotePDF(id);
      toast.success(t('pages.quotes.toast.pdfGenerated'));
    } catch {
      toast.error(t('pages.quotes.toast.actionError'));
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
      actions={isBuyer ? undefined : [{ label: t('pages.quotes.createQuote'), onClick: () => setCreateOpen(true) }]}
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
                              <DropdownMenuItem onClick={() => handleSendToClient(q.id)}>
                                <Send className="mr-2 h-4 w-4" />
                                {t('pages.quotes.actions.sendToClient')}
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => handleGeneratePDF(q.id)}>
                                <FileText className="mr-2 h-4 w-4" />
                                {t('pages.quotes.actions.generatePDF')}
                              </DropdownMenuItem>
                            </>
                          )}
                          {isBuyer && (
                            <>
                              <DropdownMenuItem onClick={() => handleApprove(q.id)}>
                                <ThumbsUp className="mr-2 h-4 w-4" />
                                {t('pages.quotes.actions.approve')}
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => handleReject(q.id)}>
                                <ThumbsDown className="mr-2 h-4 w-4" />
                                {t('pages.quotes.actions.reject')}
                              </DropdownMenuItem>
                            </>
                          )}
                          <DropdownMenuItem onClick={() => handleDownloadPDF(q.id)}>
                            <FileDown className="mr-2 h-4 w-4" />
                            {t('pages.quotes.actions.downloadPDF')}
                          </DropdownMenuItem>
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
      <CreateQuoteDialog open={createOpen} onOpenChange={setCreateOpen} />
    </PageShell>
  );
}

export default QuotesPage;
