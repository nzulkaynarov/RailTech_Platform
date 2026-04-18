import { useTranslation } from 'react-i18next';
import { Wallet } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import { usePayments } from '@/hooks/useBilling';

export function PaymentsPage() {
  const { t } = useTranslation();
  const { data: payments, isLoading } = usePayments();

  return (
    <PageShell
      title={t('paymentsPage.title')}
      description={t('paymentsPage.description')}
      icon={<Wallet className="h-5 w-5" />}
    >
      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={6} /> : (payments?.length ?? 0) === 0 ? (
            <EmptyState icon={<Wallet className="h-5 w-5" />} message={t('paymentsPage.emptyState')} />
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
                    <TableCell className="tabular-nums">{p.amount}</TableCell>
                    <TableCell>{t(`invoicesPage.method.${p.method}`)}</TableCell>
                    <TableCell>{new Date(p.paid_at).toLocaleDateString()}</TableCell>
                    <TableCell className="text-muted-foreground">{p.reference || '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}

export default PaymentsPage;
