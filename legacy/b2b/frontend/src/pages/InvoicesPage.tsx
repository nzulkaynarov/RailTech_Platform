import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { Receipt, DollarSign, ScrollText, Send, Ban, Save } from 'lucide-react';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { Separator } from '@/components/ui/separator';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { ManualModeBanner } from '@/components/Shared/ManualModeBanner';
import { RecordPaymentDialog } from '@/components/Billing/RecordPaymentDialog';
import { DealLink } from '@/components/Shared/DealLink';
import {
  Toolbar, SortableHead, Pager, useListParams, applyListParams,
} from '@/components/DataTable';
import {
  useInvoices, useGenerateAct, useIssueInvoice, useCancelInvoice, useUpdateInvoiceDraft,
} from '@/hooks/useBilling';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { useUserStore } from '@/store/userStore';
import { useCurrencyStore } from '@/store/currencyStore';
import type { InvoiceStatus } from '@/api/billingApi';
import { openableRowProps } from '@/lib/rowClick';

const STATUS_VARIANT: Record<InvoiceStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  DRAFT: 'secondary',
  ISSUED: 'outline',
  PARTIAL: 'outline',
  PAID: 'default',
  OVERDUE: 'destructive',
  CANCELLED: 'destructive',
};

const STATUS_CODES: InvoiceStatus[] = ['DRAFT', 'ISSUED', 'PARTIAL', 'PAID', 'OVERDUE', 'CANCELLED'];

export function InvoicesPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['status'] as const, { defaultOrdering: '-created_at' });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [payOpen, setPayOpen] = useState(false);

  const { data: invoices, isLoading, isError, refetch } = useInvoices(undefined);
  // Render the detail Sheet from the LIVE query cache (not a captured snapshot) so
  // issue/cancel/save/generate-act always reflect fresh data — the canon shared with
  // ContractsPage/ActsPage/OtherDocuments. A mutation invalidates ['invoices'] → the
  // list refetches → this memo re-derives `selected`.
  const selected = useMemo(
    () => (invoices ?? []).find((invoice) => invoice.id === selectedId) ?? null,
    [invoices, selectedId],
  );
  const formatCurrency = useCurrencyStore((s) => s.format);
  const generateAct = useGenerateAct();
  const issueInvoice = useIssueInvoice();
  const cancelInvoice = useCancelInvoice();
  const updateDraft = useUpdateInvoiceDraft();
  const isViewer = useIsViewerMode();
  // Recording payment is a BUYER action; issuing the Act is a SELLER action.
  const isBuyer = useUserStore((s) => s.activeStatus) === 'BUYER';
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');

  // DRAFT-only editable fields. Kept in local state, synced when the open
  // invoice changes; amounts are NOT editable (they derive from the contract).
  const [draftDue, setDraftDue] = useState('');
  const [draftNotes, setDraftNotes] = useState('');
  // Sync the editable draft fields when the opened invoice changes or its server
  // values change. Keyed on the primitives (not the memoized `selected` object,
  // whose identity churns on every cache refetch) so a background refetch that
  // returns identical data doesn't wipe an in-progress edit.
  useEffect(() => {
    setDraftDue(selected?.due_date ?? '');
    setDraftNotes(selected?.notes ?? '');
  }, [selectedId, selected?.due_date, selected?.notes]);

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

  const onGenerateAct = async () => {
    if (!selected) return;
    try {
      await generateAct.mutateAsync(selected.id);
      toast.success(t('invoicesPage.actGenerated'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onSaveDraft = async () => {
    if (!selected) return;
    try {
      // No setSelected — the mutation invalidates ['invoices'], the list refetches,
      // and `selected` re-derives from cache.
      await updateDraft.mutateAsync({
        id: selected.id, dueDate: draftDue || undefined, notes: draftNotes,
      });
      toast.success(t('invoicesPage.draftSaved'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onIssue = async () => {
    if (!selected) return;
    try {
      await issueInvoice.mutateAsync(selected.id);
      toast.success(t('invoicesPage.issued'));
      setSelectedId(null);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onCancelInvoice = async () => {
    if (!selected) return;
    try {
      // Cache-driven: cancel invalidates ['invoices'], `selected` re-derives.
      await cancelInvoice.mutateAsync(selected.id);
      toast.success(t('invoicesPage.cancelled'));
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
            if (isError) return <ErrorState onRetry={refetch} />;
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
                      <TableRow key={inv.id} {...openableRowProps(() => setSelectedId(inv.id), `${t('common.open')} ${inv.number}`)}>
                        <TableCell className="font-medium">{inv.number}</TableCell>
                        <TableCell><DealLink dealId={inv.deal} /></TableCell>
                        <TableCell className="tabular-nums">{formatCurrency(Number(inv.total_incl_vat))}</TableCell>
                        <TableCell className="tabular-nums">{formatCurrency(Number(inv.amount_paid))}</TableCell>
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
                        <TableCell className="text-right" data-row-action>
                          <Button variant="ghost" size="sm" onClick={() => setSelectedId(inv.id)} aria-label={t('common.open')}>
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
        <Sheet open={!!selected} onOpenChange={(o) => !o && setSelectedId(null)}>
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
                <div><Label>{t('invoicesPage.table.deal')}</Label><DealLink dealId={selected.deal} /></div>
                <div><Label>{t('invoicesPage.table.total')}</Label><p className="tabular-nums">{formatCurrency(Number(selected.total_incl_vat))}</p></div>
                <div><Label>{t('invoicesPage.table.paid')}</Label><p className="tabular-nums">{formatCurrency(Number(selected.amount_paid))}</p></div>
                {/* Outstanding balance — surfaced so the buyer doesn't subtract
                    total − paid by hand before paying. Highlighted when overdue. */}
                <div>
                  <Label>{t('invoicesPage.balanceDue')}</Label>
                  <p className={`tabular-nums font-medium ${selected.status === 'OVERDUE' ? 'text-destructive' : ''}`}>
                    {formatCurrency(Number(selected.balance_due))}
                  </p>
                </div>
                <div><Label>{t('invoicesPage.table.due')}</Label><p>{selected.due_date ? new Date(selected.due_date).toLocaleDateString() : '—'}</p></div>
              </div>
              <Separator />
              {selected.status === 'DRAFT' ? (
                // DRAFT — editable due date + notes; amounts come from the contract
                // and are not editable. «Issue» renders the PDF and notifies the buyer.
                <div className="flex flex-col gap-3">
                  <p className="text-xs text-muted-foreground">{t('invoicesPage.amountsFromContract')}</p>
                  <div className="space-y-1.5">
                    <Label htmlFor="inv-draft-due">{t('invoicesPage.dueDate')}</Label>
                    <Input
                      id="inv-draft-due"
                      type="date"
                      value={draftDue}
                      onChange={(e) => setDraftDue(e.target.value)}
                      disabled={isViewer}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="inv-draft-notes">{t('invoicesPage.notes')}</Label>
                    <Textarea
                      id="inv-draft-notes"
                      value={draftNotes}
                      onChange={(e) => setDraftNotes(e.target.value)}
                      disabled={isViewer}
                    />
                  </div>
                  <Button
                    variant="outline"
                    onClick={onSaveDraft}
                    disabled={updateDraft.isPending || isViewer}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <Save className="mr-2 h-4 w-4" />
                    {t('invoicesPage.saveDraft')}
                  </Button>
                  <Button
                    onClick={onIssue}
                    disabled={issueInvoice.isPending || isViewer}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <Send className="mr-2 h-4 w-4" />
                    {t('invoicesPage.issue')}
                  </Button>
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {/* CANCELLED invoices are view-only — no PDF/actions. */}
                  {selected.status !== 'CANCELLED' && selected.pdf_url && (
                    <DocumentActions
                      request={() => ({ path: `crm/invoices/${selected.id}/download-pdf/` })}
                      filenameBase={`RailTech_Invoice_${selected.id}`}
                      size="default"
                    />
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
                  {!isBuyer && selected.status !== 'CANCELLED' && (
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
                  {/* Cancel an issued-but-unpaid invoice; backend refuses PAID/PARTIAL. */}
                  {selected.status !== 'PAID' && selected.status !== 'CANCELLED' && (
                    <Button
                      variant="outline"
                      onClick={onCancelInvoice}
                      disabled={cancelInvoice.isPending || isViewer}
                      title={isViewer ? viewerTip : undefined}
                    >
                      <Ban className="mr-2 h-4 w-4" />
                      {t('invoicesPage.cancel')}
                    </Button>
                  )}
                </div>
              )}
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

      {/* Canonical payment recorder — shows the outstanding balance, blocks
          overpayment, and accepts a proof-of-payment file. Replaces the former
          bespoke inline form that did none of those. */}
      <RecordPaymentDialog
        open={payOpen}
        onOpenChange={setPayOpen}
        defaultInvoiceId={selected?.id}
        onRecorded={() => { setPayOpen(false); refetch(); }}
      />
    </PageShell>
  );
}

export default InvoicesPage;
