import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { formatDate } from '@/lib/formatLocale';
import { Receipt, DollarSign, ScrollText, Send, Ban, Save } from 'lucide-react';
import { DocumentActions } from '@/components/Shared/DocumentActions';
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
import { PageShell } from './shared/PageShell';
import { DocumentRegistry, useDocumentCoreColumns } from '@/components/Documents/DocumentRegistry';
import { ManualModeBanner } from '@/components/Shared/ManualModeBanner';
import { RecordPaymentDialog } from '@/components/Billing/RecordPaymentDialog';
import { DealLink } from '@/components/Shared/DealLink';
import { Toolbar, useListParams, applyListParams } from '@/components/DataTable';
import {
  useInvoices, useGenerateAct, useIssueInvoice, useCancelInvoice, useUpdateInvoiceDraft,
} from '@/hooks/useBilling';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { useCurrencyStore } from '@/store/currencyStore';
import type { Invoice, InvoiceStatus } from '@/api/billingApi';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';

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
  const [cancelOpen, setCancelOpen] = useState(false);

  const { data: invoices, isLoading, isError, refetch } = useInvoices(undefined);

  // WP-G2 — deep link `#invoices?open=<id>` (the create-invoice wizard lands the seller here on
  // the new DRAFT's editor). Open the Sheet from the id, then strip the param so a manual close /
  // reload doesn't reopen it. `selected` derives from the live list cache, so the Sheet appears
  // once the just-created invoice is present after the create mutation's invalidation.
  useEffect(() => {
    const applyDeepLink = () => {
      const query = window.location.hash.split('?')[1];
      const openId = query ? new URLSearchParams(query).get('open') : null;
      const parsed = openId ? Number(openId) : NaN;
      if (Number.isFinite(parsed) && parsed > 0) {
        setSelectedId(parsed);
        window.history.replaceState(
          { ...(window.history.state || {}) },
          '',
          `${window.location.pathname}${window.location.search}#invoices`,
        );
      }
    };
    applyDeepLink();
    window.addEventListener('hashchange', applyDeepLink);
    return () => window.removeEventListener('hashchange', applyDeepLink);
  }, []);
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
  // Оплата — действие ПОКУПАТЕЛЯ, выпуск акта — ПРОДАВЦА. Сторону по каждому счёту считает
  // сервер (`viewer_can_pay` / `viewer_can_manage`), как у договоров с viewer_can_sign_*:
  // прежний вывод из activeStatus брал первый тип компании, и посредник, который и покупает,
  // и продаёт, не видел кнопки «Сформировать акт» вовсе.
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
    // Cache-driven: cancel invalidates ['invoices'], `selected` re-derives.
    await cancelInvoice.mutateAsync(selected.id);
    toast.success(t('invoicesPage.cancelled'));
  };

  const { items: pageItems, total } = applyListParams(invoices ?? [], listParams, {
    searchFields: (i) => [i.number, String(i.deal)],
    filterPredicates: { status: (i, v) => i.status === v },
    sortAccessors: {
      number: (i) => i.number,
      total: (i) => Number(i.total_incl_vat),
      paid: (i) => Number(i.amount_paid),
      issued: (i) => i.issued_at ?? '',
      due: (i) => i.due_date ?? '',
      created_at: (i) => i.created_at,
    },
  });

  // Ядро колонок в общем порядке; «Оплачено» и «Срок оплаты» — специфика счёта, приставлена
  // к понятным якорям (после суммы и после даты выставления), а не вместо ядра.
  const columns = useDocumentCoreColumns<Invoice>({
    number: (inv) => <span className="font-medium">{inv.number}</span>,
    deal: (inv) => <DealLink dealId={inv.deal} />,
    status: (inv) => <Badge variant={STATUS_VARIANT[inv.status]}>{t(`invoicesPage.status.${inv.status}`)}</Badge>,
    total: (inv) => <span className="tabular-nums">{formatCurrency(Number(inv.total_incl_vat))}</span>,
    date: (inv) => (inv.issued_at ? formatDate(inv.issued_at) : '—'),
    actions: (inv) => (
      <DocumentActions
        request={() => ({ path: `crm/invoices/${inv.id}/download-pdf/` })}
        filenameBase={`RailTech_Invoice_${inv.id}`}
        variant="ghost"
        iconOnly
      />
    ),
    sortKeys: { number: 'number', total: 'total', date: 'issued' },
    dateHeader: t('invoicesPage.table.issued'),
    insertAfter: {
      total: [{
        id: 'paid',
        header: t('invoicesPage.table.paid'),
        sortKey: 'paid',
        className: 'text-right',
        cell: (inv: Invoice) => <span className="tabular-nums">{formatCurrency(Number(inv.amount_paid))}</span>,
      }],
      date: [{
        id: 'due',
        header: t('invoicesPage.table.due'),
        sortKey: 'due',
        className: 'text-xs text-muted-foreground',
        cell: (inv: Invoice) => (inv.due_date ? formatDate(inv.due_date) : '—'),
      }],
    },
  });

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
      <DocumentRegistry
        rows={pageItems}
        getRowId={(inv) => inv.id}
        columns={columns}
        onRowClick={(inv) => setSelectedId(inv.id)}
        isLoading={isLoading}
        isError={isError}
        onRetry={refetch}
        emptyIcon={<Receipt className="h-5 w-5" />}
        emptyMessage={t('invoicesPage.emptyState')}
        sorting={{ ordering: listParams.ordering, onToggle: listParams.toggleOrdering }}
        pagination={{ page: listParams.page, pageSize: listParams.pageSize, total, onPageChange: listParams.setPage }}
      />

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
                <div><Label>{t('invoicesPage.table.due')}</Label><p>{selected.due_date ? formatDate(selected.due_date) : '—'}</p></div>
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
                  {/* Аннулированный счёт — только просмотр, PDF по нему не выдаётся. В остальных
                      случаях кнопка не ждёт готового файла: сервер ставит рендер и отвечает 202
                      (ARCH-03). Раньше условие требовало уже существующий PDF, и счёт было не
                      получить именно до отрисовки (аудит UI, U3). */}
                  {selected.status !== 'CANCELLED' && (
                    <DocumentActions
                      request={() => ({ path: `crm/invoices/${selected.id}/download-pdf/` })}
                      filenameBase={`RailTech_Invoice_${selected.id}`}
                      size="default"
                    />
                  )}
                  {selected.viewer_can_pay && (
                    <Button
                      onClick={() => setPayOpen(true)}
                      disabled={isViewer}
                      title={isViewer ? viewerTip : undefined}
                    >
                      <DollarSign className="mr-2 h-4 w-4" />
                      {t('invoicesPage.recordPayment')}
                    </Button>
                  )}
                  {selected.viewer_can_manage && selected.status !== 'CANCELLED' && (
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
                  {/* Аннулирование счёта необратимо (бэкенд отказывает по PAID/PARTIAL), а
                      кнопка стояла рядом с обычными действиями и срабатывала с первого клика
                      (аудит UI, U4). Теперь она открывает подтверждение. */}
                  {selected.status !== 'PAID' && selected.status !== 'CANCELLED' && (
                    <Button
                      variant="outline"
                      onClick={() => setCancelOpen(true)}
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
                          {/* Позиции печатались сырой строкой API («1440000.00») рядом с
                              форматированным итогом «UZS 32,256,000.00» — глазами 17-08. */}
                          <TableCell className="text-right tabular-nums">{formatCurrency(Number(it.unit_price_excl_vat))}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatCurrency(Number(it.line_total_excl_vat))}</TableCell>
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

      <ConfirmActionDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        title={t('invoicesPage.cancelConfirmTitle')}
        description={t('invoicesPage.cancelConfirmDescription', { number: selected?.number ?? '' })}
        variant="destructive"
        confirmLabel={t('invoicesPage.cancel')}
        onConfirm={onCancelInvoice}
        translateError={(code) => translateApiError(code)}
      />
    </PageShell>
  );
}

export default InvoicesPage;
