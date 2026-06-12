import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { Receipt, Download, DollarSign, ScrollText } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import { ManualModeBanner } from '@/components/Shared/ManualModeBanner';
import {
  Toolbar, SortableHead, Pager, useListParams, applyListParams,
} from '@/components/DataTable';
import {
  useInvoices, useRecordPayment, useGenerateAct,
} from '@/hooks/useBilling';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { useUserStore } from '@/store/userStore';
import { invoicesApi } from '@/api/billingApi';
import type { Invoice, InvoiceStatus } from '@/api/billingApi';

const STATUS_VARIANT: Record<InvoiceStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  DRAFT: 'secondary',
  ISSUED: 'outline',
  PARTIAL: 'outline',
  PAID: 'default',
  OVERDUE: 'destructive',
  CANCELLED: 'destructive',
};

const STATUS_CODES: InvoiceStatus[] = ['DRAFT', 'ISSUED', 'PARTIAL', 'PAID', 'OVERDUE', 'CANCELLED'];
const METHODS = ['BANK_TRANSFER', 'CARD', 'CASH', 'OTHER'] as const;

export function InvoicesPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['status'] as const, { defaultOrdering: '-created_at' });
  const [selected, setSelected] = useState<Invoice | null>(null);
  const [payOpen, setPayOpen] = useState(false);
  const [payForm, setPayForm] = useState({
    amount: '',
    paid_at: new Date().toISOString().slice(0, 10),
    method: 'BANK_TRANSFER',
    reference: '',
  });

  const { data: invoices, isLoading } = useInvoices(undefined);
  const recordPayment = useRecordPayment();
  const generateAct = useGenerateAct();
  const isViewer = useIsViewerMode();
  // Recording payment is a BUYER action; issuing the Act is a SELLER action.
  const isBuyer = useUserStore((s) => s.activeStatus) === 'BUYER';
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');

  const stats = useMemo(() => {
    const list = invoices ?? [];
    return [
      { label: t('invoicesPage.stats.total'), value: String(list.length) },
      {
        label: t('invoicesPage.stats.unpaid'),
        value: String(list.filter((i) => i.status !== 'PAID' && i.status !== 'CANCELLED').length),
      },
      {
        label: t('invoicesPage.stats.paid'),
        value: String(list.filter((i) => i.status === 'PAID').length),
      },
    ];
  }, [invoices, t]);

  const onRecordPayment = async () => {
    if (!selected || !payForm.amount || !payForm.paid_at) return;
    try {
      await recordPayment.mutateAsync({
        invoiceId: selected.id,
        amount: payForm.amount,
        paidAt: payForm.paid_at,
        method: payForm.method,
        reference: payForm.reference,
      });
      toast.success(t('invoicesPage.paymentRecorded'));
      setPayOpen(false);
      setPayForm({
        amount: '', paid_at: new Date().toISOString().slice(0, 10),
        method: 'BANK_TRANSFER', reference: '',
      });
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onGenerateAct = async () => {
    if (!selected) return;
    try {
      await generateAct.mutateAsync(selected.id);
      toast.success(t('invoicesPage.actGenerated'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <PageShell
      title={t('invoicesPage.title')}
      description={t('invoicesPage.description')}
      icon={<Receipt className="h-5 w-5" />}
      stats={stats}
    >
      <ManualModeBanner kind="payment" />
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('invoicesPage.searchPlaceholder')}
        filters={[
          {
            key: 'status',
            value: listParams.filters.status,
            onChange: (v) => listParams.setFilter('status', v),
            allLabel: t('invoicesPage.allStatuses'),
            options: STATUS_CODES.map((s) => ({ value: s, label: t(`invoicesPage.status.${s}`) })),
          },
        ]}
      />
      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(invoices ?? [], listParams, {
              searchFields: (i) => [i.number, String(i.deal)],
              filterPredicates: {
                status: (i, v) => i.status === v,
              },
              sortAccessors: {
                number: (i) => i.number,
                total: (i) => Number(i.total_incl_vat),
                paid: (i) => Number(i.amount_paid),
                issued: (i) => i.issued_at ?? '',
                due: (i) => i.due_date ?? '',
                created_at: (i) => i.created_at,
              },
            });
            if (isLoading) return <LoadingRows rows={6} />;
            if (!pageItems.length) {
              return <EmptyState icon={<Receipt className="h-5 w-5" />} message={t('invoicesPage.emptyState')} />;
            }
            return (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead sortKey="number" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('invoicesPage.table.number')}
                      </SortableHead>
                      <TableHead>{t('invoicesPage.table.deal')}</TableHead>
                      <SortableHead sortKey="total" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('invoicesPage.table.total')}
                      </SortableHead>
                      <SortableHead sortKey="paid" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('invoicesPage.table.paid')}
                      </SortableHead>
                      <TableHead>{t('invoicesPage.table.status')}</TableHead>
                      <SortableHead sortKey="issued" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('invoicesPage.table.issued')}
                      </SortableHead>
                      <SortableHead sortKey="due" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('invoicesPage.table.due')}
                      </SortableHead>
                      <TableHead className="text-right">{t('invoicesPage.table.actions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pageItems.map((inv) => (
                      <TableRow key={inv.id}>
                        <TableCell className="font-medium">{inv.number}</TableCell>
                        <TableCell>#{inv.deal}</TableCell>
                        <TableCell className="tabular-nums">{inv.total_incl_vat}</TableCell>
                        <TableCell className="tabular-nums">{inv.amount_paid}</TableCell>
                        <TableCell>
                          <Badge variant={STATUS_VARIANT[inv.status]}>
                            {t(`invoicesPage.status.${inv.status}`)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {inv.issued_at ? new Date(inv.issued_at).toLocaleDateString() : '—'}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {inv.due_date ? new Date(inv.due_date).toLocaleDateString() : '—'}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button variant="ghost" size="sm" onClick={() => setSelected(inv)}>
                            <Receipt className="h-4 w-4" />
                          </Button>
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

      {selected && (
        <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
          <SheetContent className="overflow-y-auto sm:max-w-lg">
            <SheetHeader>
              <SheetTitle>{selected.number}</SheetTitle>
              <SheetDescription>
                <Badge variant={STATUS_VARIANT[selected.status]}>
                  {t(`invoicesPage.status.${selected.status}`)}
                </Badge>
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-4 p-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><Label>{t('invoicesPage.table.deal')}</Label><p>#{selected.deal}</p></div>
                <div><Label>{t('invoicesPage.table.total')}</Label><p className="tabular-nums">{selected.total_incl_vat}</p></div>
                <div><Label>{t('invoicesPage.table.paid')}</Label><p className="tabular-nums">{selected.amount_paid}</p></div>
                <div><Label>{t('invoicesPage.table.due')}</Label><p>{selected.due_date ? new Date(selected.due_date).toLocaleDateString() : '—'}</p></div>
              </div>
              <Separator />
              <div className="flex flex-col gap-2">
                {selected.pdf_url && (
                  <Button
                    variant="outline"
                    onClick={async () => {
                      try {
                        await invoicesApi.downloadPdf(selected.id);
                      } catch (e) {
                        toast.error(translateApiError(e));
                      }
                    }}
                  >
                    <Download className="mr-2 h-4 w-4" />
                    {t('invoicesPage.downloadPdf')}
                  </Button>
                )}
                {isBuyer && selected.status !== 'PAID' && selected.status !== 'CANCELLED' && (
                  <Button
                    onClick={() => setPayOpen(true)}
                    disabled={isViewer}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <DollarSign className="mr-2 h-4 w-4" />
                    {t('invoicesPage.recordPayment')}
                  </Button>
                )}
                {!isBuyer && (
                  <Button
                    variant="outline"
                    onClick={onGenerateAct}
                    disabled={generateAct.isPending || isViewer}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <ScrollText className="mr-2 h-4 w-4" />
                    {t('invoicesPage.generateAct')}
                  </Button>
                )}
              </div>
              {selected.items?.length > 0 && (
                <div>
                  <Label>{t('invoicesPage.items')}</Label>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>#</TableHead>
                        <TableHead>{t('invoicesPage.itemHeaders.description')}</TableHead>
                        <TableHead>{t('invoicesPage.itemHeaders.qty')}</TableHead>
                        <TableHead>{t('invoicesPage.itemHeaders.price')}</TableHead>
                        <TableHead>{t('invoicesPage.itemHeaders.line')}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {selected.items.map((it, idx) => (
                        <TableRow key={it.id}>
                          <TableCell>{idx + 1}</TableCell>
                          <TableCell>{it.description}</TableCell>
                          <TableCell>{it.quantity}</TableCell>
                          <TableCell className="tabular-nums">{it.unit_price_excl_vat}</TableCell>
                          <TableCell className="tabular-nums">{it.line_total_excl_vat}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
            <SheetFooter />
          </SheetContent>
        </Sheet>
      )}

      <Sheet open={payOpen} onOpenChange={setPayOpen}>
        <SheetContent className="sm:max-w-md">
          <SheetHeader>
            <SheetTitle>{t('invoicesPage.recordPayment')}</SheetTitle>
            <SheetDescription>{selected?.number}</SheetDescription>
          </SheetHeader>
          <div className="space-y-3 p-4">
            <div>
              <Label htmlFor="amt">{t('invoicesPage.form.amount')}</Label>
              <Input id="amt" type="number" step="0.01" value={payForm.amount}
                     onChange={(e) => setPayForm({ ...payForm, amount: e.target.value })} />
            </div>
            <div>
              <Label htmlFor="paidAt">{t('invoicesPage.form.paidAt')}</Label>
              <Input id="paidAt" type="date" value={payForm.paid_at}
                     onChange={(e) => setPayForm({ ...payForm, paid_at: e.target.value })} />
            </div>
            <div>
              <Label>{t('invoicesPage.form.method')}</Label>
              <Select value={payForm.method} onValueChange={(v) => setPayForm({ ...payForm, method: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {METHODS.map((m) => (
                    <SelectItem key={m} value={m}>{t(`invoicesPage.method.${m}`)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="ref">{t('invoicesPage.form.reference')}</Label>
              <Input id="ref" value={payForm.reference}
                     onChange={(e) => setPayForm({ ...payForm, reference: e.target.value })} />
            </div>
          </div>
          <SheetFooter>
            <Button
              onClick={onRecordPayment}
              disabled={recordPayment.isPending || !payForm.amount || isViewer}
              title={isViewer ? viewerTip : undefined}
              className="w-full"
            >
              {t('invoicesPage.recordPayment')}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </PageShell>
  );
}

export default InvoicesPage;
