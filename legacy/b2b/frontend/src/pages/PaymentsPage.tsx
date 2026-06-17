import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Wallet, Plus } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { usePayments } from '@/hooks/useBilling';
import { RecordPaymentDialog } from '@/components/Billing/RecordPaymentDialog';
import { useUserStore } from '@/store/userStore';
import { useCurrencyStore } from '@/store/currencyStore';

export function PaymentsPage() {
  const { t } = useTranslation();
  const { data: payments, isLoading, isError, refetch } = usePayments();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const [recordOpen, setRecordOpen] = useState(false);
  // Recording a payment is a BUYER action (the client pays the invoice).
  const isBuyer = useUserStore((s) => s.activeStatus) === 'BUYER';

  const stats = [
    { label: t('paymentsPage.stats.total'), value: String(payments?.length ?? 0) },
  ];

  return (
    <PageShell
      title={t('paymentsPage.title')}
      description={t('paymentsPage.description')}
      icon={<Wallet className="h-5 w-5" />}
      stats={stats}
    >
      {isBuyer && (
        <div className="flex items-center justify-end">
          <Button onClick={() => setRecordOpen(true)} className="gap-2">
            <Plus className="h-4 w-4" aria-hidden="true" />
            {t('recordPayment.cta')}
          </Button>
        </div>
      )}
      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={6} /> : isError ? <ErrorState onRetry={refetch} /> : (payments?.length ?? 0) === 0 ? (
            <EmptyState
              icon={<Wallet className="h-5 w-5" />}
              message={t('paymentsPage.emptyState')}
              action={isBuyer ? { label: t('recordPayment.cta'), onClick: () => setRecordOpen(true) } : undefined}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('paymentsPage.table.invoice')}</TableHead>
                  <TableHead>{t('paymentsPage.table.amount')}</TableHead>
                  <TableHead>{t('paymentsPage.table.method')}</TableHead>
                  <TableHead>{t('paymentsPage.table.paidAt')}</TableHead>
                  <TableHead>{t('paymentsPage.table.reference')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(payments ?? []).map((p) => (
                  <TableRow key={p.id}>
                    <TableCell>#{p.invoice}</TableCell>
                    <TableCell className="tabular-nums">{formatCurrency(Number(p.amount))}</TableCell>
                    <TableCell>{t(`invoicesPage.method.${p.method}`, p.method)}</TableCell>
                    <TableCell>{new Date(p.paid_at).toLocaleDateString()}</TableCell>
                    <TableCell className="text-muted-foreground">{p.reference || '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
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
