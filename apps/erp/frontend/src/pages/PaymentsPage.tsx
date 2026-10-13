import { useState } from 'react'; import { useTranslation } from 'react-i18next'; import { Wallet } from 'lucide-react'; import { Card, CardContent } from '@/components/ui/card'; import { formatDate } from '@/lib/formatLocale'; import {   Table, TableBody, TableCell, TableHead, TableHeader, TableRow, } from '@/components/ui/table'; import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell'; import { Toolbar, SortableHead, Pager } from '@/components/DataTable';
import { useListParams, applyListParams } from '@/components/DataTable/listParams';
import { usePayments } from '@/hooks/useBilling';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { RecordPaymentDialog } from '@/components/Billing/RecordPaymentDialog';
import { useUserStore } from '@/store/userStore';
import { useCurrencyStore } from '@/store/currencyStore';

export function PaymentsPage() {
  const { t } = useTranslation();
  const { data: payments, isLoading, isError, refetch } = usePayments();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const [recordOpen, setRecordOpen] = useState(false);
  // Оплату записывает покупающая сторона. Гейтим по СПОСОБНОСТИ члена (`can_buy`), а не по
  // контексту отображения: `activeStatus` — первый тип компании, и посредник, который и
  // покупает, и продаёт, кнопки не видел. Тот же образец, что в DocumentCreateWizard.
  const isBuyer = useUserStore((s) => s.capabilities.can_buy);
  const listParams = useListParams([] as const, { urlKey: 'payments', defaultOrdering: '-paid_at' });

  const stats = [
    { label: t('paymentsPage.stats.total'), value: String(payments?.length ?? 0) },
  ];

  return (
    <PageShell
      title={t('paymentsPage.title')}
      description={t('paymentsPage.description')}
      icon={<Wallet className="h-5 w-5" />}
      stats={stats}
      statsError={isError}
      actions={isBuyer ? [{ label: t('recordPayment.cta'), onClick: () => setRecordOpen(true) }] : undefined}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('paymentsPage.table.invoice')}
      />
      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(payments ?? [], listParams, {
              searchFields: (p) => [String(p.invoice), p.reference ?? ''],
              sortAccessors: {
                invoice: (p) => p.invoice,
                amount: (p) => Number(p.amount) || 0,
                paid_at: (p) => p.paid_at ?? '',
              },
            });
            if (isLoading) return <LoadingRows rows={6} />;
            if (isError) return <ErrorState onRetry={refetch} />;
            if (!pageItems.length) {
              return (
                <EmptyState
                  icon={<Wallet className="h-5 w-5" />}
                  message={t('paymentsPage.emptyState')}
                  action={isBuyer ? { label: t('recordPayment.cta'), onClick: () => setRecordOpen(true) } : undefined}
                />
              );
            }
            return (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead sortKey="invoice" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('paymentsPage.table.invoice')}
                      </SortableHead>
                      <SortableHead sortKey="amount" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('paymentsPage.table.amount')}
                      </SortableHead>
                      <TableHead>{t('paymentsPage.table.method')}</TableHead>
                      <SortableHead sortKey="paid_at" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('paymentsPage.table.paidAt')}
                      </SortableHead>
                      <TableHead>{t('paymentsPage.table.reference')}</TableHead>
                      <TableHead className="text-right">{t('paymentsPage.table.receipt')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pageItems.map((p) => (
                      <TableRow key={p.id}>
                        <TableCell>#{p.invoice}</TableCell>
                        <TableCell className="tabular-nums">{formatCurrency(Number(p.amount))}</TableCell>
                        <TableCell>{t(`invoicesPage.method.${p.method}`, p.method)}</TableCell>
                        <TableCell>{formatDate(p.paid_at)}</TableCell>
                        <TableCell className="text-muted-foreground">{p.reference || '—'}</TableCell>
                        <TableCell className="text-right">
                          {/* D2a: квитанция — печатный артефакт платежа (Odoo Payment Receipt). */}
                          <DocumentActions
                            request={() => ({ path: `crm/payments/${p.id}/download-receipt/` })}
                            filenameBase={`RailTech_Receipt_${p.receipt_number || p.id}`}
                            size="sm"
                          />
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

      <RecordPaymentDialog
        open={recordOpen}
        onOpenChange={setRecordOpen}
        onRecorded={() => refetch()}
      />
    </PageShell>
  );
}

export default PaymentsPage;
