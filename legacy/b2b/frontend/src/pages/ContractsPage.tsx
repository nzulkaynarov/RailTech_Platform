import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { formatDate, formatDateTime } from '@/lib/formatLocale';
import { extractBlobErrorCode, fetchDocumentBlob, saveBlob } from '@/lib/documents';
import { PenLine, Upload, Download, Receipt, Ban, FileSignature, ShieldAlert } from 'lucide-react';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { PageShell } from './shared/PageShell';
import { DocumentRegistry, useDocumentCoreColumns } from '@/components/Documents/DocumentRegistry';
import { ManualModeBanner } from '@/components/Shared/ManualModeBanner';
import { Toolbar, useListParams, applyListParams } from '@/components/DataTable';
import {
  useContracts, useSignContractClient, useSignContractManager,
  useUploadSignedContract, useCancelContract, useForceCancelContract, useGenerateInvoice,
} from '@/hooks/useBilling';
import { useUserStore } from '@/store/userStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import type { Contract, ContractStatus } from '@/api/contractsApi';
import { ContractWordingSection } from '@/components/CRM/ContractWordingSection';
import { DealLink } from '@/components/Shared/DealLink';
import { DocumentCheck } from '@/components/CRM/DocumentCheck';

const STATUS_VARIANT: Record<ContractStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  DRAFT: 'secondary',
  PENDING_CLIENT: 'outline',
  PENDING_MANAGER: 'outline',
  SIGNED: 'default',
  CANCELLED: 'destructive',
};

const STATUS_CODES: ContractStatus[] = [
  'DRAFT', 'PENDING_CLIENT', 'PENDING_MANAGER', 'SIGNED', 'CANCELLED',
];

export function ContractsPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['status'] as const, { defaultOrdering: '-created_at' });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Contract | null>(null);

  // Deep-link support: `#contracts?open=<id>` (used by the buyer's post-accept panel,
  // Wave A2) auto-opens that contract's detail sheet. Parsed from the hash query — the
  // SPA is hash-routed, so window.location.search is not where our params live.
  useEffect(() => {
    const query = window.location.hash.split('?')[1];
    if (!query) return;
    const openId = Number(new URLSearchParams(query).get('open'));
    if (Number.isFinite(openId) && openId > 0) setSelectedId(openId);
  }, []);

  const [cancelReason, setCancelReason] = useState('');
  const [forceCancelTarget, setForceCancelTarget] = useState<Contract | null>(null);
  const [forceCancelReason, setForceCancelReason] = useState('');

  const role = useUserStore((s) => s.role);
  const isPlatformAdmin = role === 'ADMIN';
  // Contract is double-signed: the buyer signs as client, the seller as manager. Which side the
  // viewer may sign is server-computed per contract (viewer_can_sign_client/manager) — NOT the
  // page context — so a dual buy+sell company gets the correct button either way.
  const isViewer = useIsViewerMode();
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');
  const { data: contracts, isLoading, isError, refetch } = useContracts(undefined);
  const generateInvoice = useGenerateInvoice();

  // Download the uploaded signed copy (the endpoint exists both here and for acts — the file was
  // uploadable but never downloadable back, a plain governance gap). The file may be a PDF or an
  // image, so it saves as-is rather than assuming a PDF.
  const onDownloadSigned = async (contract: Contract) => {
    try {
      const blob = await fetchDocumentBlob(`crm/contracts/${contract.id}/download-signed/`);
      const ext = blob.type.includes('pdf') ? 'pdf' : (blob.type.split('/')[1] || 'bin');
      saveBlob(blob, `RailTech_Contract_${contract.id}_signed.${ext}`);
    } catch (err) {
      // Surface the real backend code (403/404/expiry) so permission/not-found reads differently
      // from a network blip. Blob-response bodies aren't plain JSON — parse the code out first.
      const code = await extractBlobErrorCode(err);
      toast.error(code ? translateApiError(code) : t('errors.operationFailed'));
    }
  };

  const onCreateInvoice = async (contract: Contract) => {
    try {
      await generateInvoice.mutateAsync({ contractId: contract.id });
      toast.success(t('contractsPage.invoiceCreated'));
      // Take the user to the invoices registry — closes the "created it, now where?"
      // dead-end. The just-created invoice is a DRAFT there.
      window.location.hash = 'invoices';
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };
  const formatCurrency = useCurrencyStore((s) => s.format);
  const signClient = useSignContractClient();
  const signManager = useSignContractManager();
  const uploadSigned = useUploadSignedContract();
  const cancelMut = useCancelContract();
  const forceCancelMut = useForceCancelContract();

  // P2-2: render the detail panel from the LIVE query cache (not a captured
  // snapshot). A sign/cancel mutation invalidates ['contracts'] → the list refetches
  // → this memo re-derives `selected` → the panel reflects the new signature without
  // a close+reopen.
  const selected = useMemo(
    () => (contracts ?? []).find((contract) => contract.id === selectedId) ?? null,
    [contracts, selectedId],
  );
  // Side indicator: which side the VIEWER acts as on THIS contract — derived from the
  // server-computed sign hints (viewer_can_sign_client/manager), not the SPA page context, so a
  // dual buy+sell company sees the correct side per contract regardless of which context it
  // landed in. Null when the viewer is neither side (platform viewer / non-signer).
  const sideBadgeFor = (contract: Contract) => {
    const side: 'buyer' | 'seller' | null = contract.viewer_can_sign_client
      ? 'buyer'
      : contract.viewer_can_sign_manager
        ? 'seller'
        : null;
    if (!side) return null;
    return (
      <Badge
        variant="outline"
        data-side={side}
        className={side === 'buyer' ? 'border-info text-info' : 'border-primary text-primary'}
      >
        {t(`contractsPage.side.${side}`)}
      </Badge>
    );
  };

  const stats = useMemo(() => {
    const list = contracts ?? [];
    return [
      { label: t('contractsPage.stats.total'), value: String(list.length) },
      {
        label: t('contractsPage.stats.pending'),
        value: String(list.filter((c) => c.status === 'PENDING_CLIENT' || c.status === 'PENDING_MANAGER').length),
      },
      {
        label: t('contractsPage.stats.signed'),
        value: String(list.filter((c) => c.status === 'SIGNED').length),
      },
    ];
  }, [contracts, t]);

  const onSignClient = async (c: Contract) => {
    try {
      await signClient.mutateAsync(c.id);
      toast.success(t('contractsPage.signedClient'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onSignManager = async (c: Contract) => {
    try {
      await signManager.mutateAsync(c.id);
      toast.success(t('contractsPage.signedManager'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onUploadFile = async (c: Contract, file: File) => {
    try {
      await uploadSigned.mutateAsync({ id: c.id, file });
      toast.success(t('contractsPage.uploadedSigned'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onCancel = async () => {
    if (!cancelTarget) return;
    try {
      await cancelMut.mutateAsync({ id: cancelTarget.id, reason: cancelReason });
      toast.success(t('contractsPage.cancelled'));
      setCancelTarget(null);
      setCancelReason('');
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onForceCancel = async () => {
    if (!forceCancelTarget) return;
    if (!forceCancelReason.trim()) {
      toast.error(t('contractsPage.forceCancelReasonRequired'));
      return;
    }
    try {
      await forceCancelMut.mutateAsync({ id: forceCancelTarget.id, reason: forceCancelReason });
      toast.success(t('contractsPage.forceCancelled'));
      setForceCancelTarget(null);
      setForceCancelReason('');
      setSelectedId(null);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const { items: pageItems, total } = applyListParams(contracts ?? [], listParams, {
    searchFields: (c) => [c.number, String(c.deal)],
    filterPredicates: { status: (c, v) => c.status === v },
    sortAccessors: {
      number: (c) => c.number,
      deal: (c) => c.deal,
      total: (c) => Number(c.total_amount),
      status: (c) => c.status,
      created_at: (c) => c.created_at,
    },
  });

  // Ядро колонок в общем порядке; «Сторона» — специфика договора, приставлена после сделки.
  const columns = useDocumentCoreColumns<Contract>({
    number: (c) => <span className="font-medium">{c.number}</span>,
    deal: (c) => <DealLink dealId={c.deal} />,
    status: (c) => <Badge variant={STATUS_VARIANT[c.status]}>{t(`contractsPage.status.${c.status}`)}</Badge>,
    total: (c) => <span className="tabular-nums">{formatCurrency(Number(c.total_amount))}</span>,
    date: (c) => formatDate(c.created_at),
    actions: (c) => (
      <DocumentActions
        request={() => ({ path: `crm/contracts/${c.id}/download-pdf/` })}
        filenameBase={`RailTech_Contract_${c.id}`}
        variant="ghost"
        iconOnly
      />
    ),
    sortKeys: { number: 'number', total: 'total', date: 'created_at' },
    dateHeader: t('contractsPage.table.created'),
    insertAfter: {
      deal: [{
        id: 'side',
        header: t('contractsPage.table.side'),
        cell: (c: Contract) => sideBadgeFor(c),
      }],
    },
  });

  return (
    <PageShell
      title={t('contractsPage.title')}
      description={t('contractsPage.description')}
      icon={<FileSignature className="h-5 w-5" />}
      stats={stats}
    >
      <ManualModeBanner kind="esign" />
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('contractsPage.searchPlaceholder')}
        filters={[
          {
            key: 'status',
            value: listParams.filters.status,
            onChange: (v) => listParams.setFilter('status', v),
            allLabel: t('contractsPage.allStatuses'),
            options: STATUS_CODES.map((s) => ({ value: s, label: t(`contractsPage.status.${s}`) })),
          },
        ]}
      />

      <DocumentRegistry
        rows={pageItems}
        getRowId={(c) => c.id}
        columns={columns}
        onRowClick={(c) => setSelectedId(c.id)}
        isLoading={isLoading}
        isError={isError}
        onRetry={refetch}
        emptyIcon={<FileSignature className="h-5 w-5" />}
        emptyMessage={t('contractsPage.emptyState')}
        emptyHint={t('contractsPage.emptyStateHint')}
        sorting={{ ordering: listParams.ordering, onToggle: listParams.toggleOrdering }}
        pagination={{ page: listParams.page, pageSize: listParams.pageSize, total, onPageChange: listParams.setPage }}
      />

      {selected && (
        <Sheet open={!!selected} onOpenChange={(o) => !o && setSelectedId(null)}>
          <SheetContent className="overflow-y-auto sm:max-w-lg">
            <SheetHeader>
              <SheetTitle>{selected.number}</SheetTitle>
              <SheetDescription className="flex flex-wrap items-center gap-2">
                <Badge variant={STATUS_VARIANT[selected.status]}>
                  {t(`contractsPage.status.${selected.status}`)}
                </Badge>
                {sideBadgeFor(selected)}
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-4 p-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><Label>{t('contractsPage.table.deal')}</Label><DealLink dealId={selected.deal} /></div>
                <div><Label>{t('contractsPage.table.total')}</Label><p className="tabular-nums">{formatCurrency(Number(selected.total_amount))}</p></div>
                <div>
                  <Label>{t('contractsPage.signClient')}</Label>
                  <p className="text-muted-foreground">
                    {selected.client_signed_at
                      ? `${selected.client_signer_name} · ${formatDateTime(selected.client_signed_at)}`
                      : '—'}
                  </p>
                </div>
                <div>
                  <Label>{t('contractsPage.signManager')}</Label>
                  <p className="text-muted-foreground">
                    {selected.manager_signed_at
                      ? `${selected.manager_signer_name} · ${formatDateTime(selected.manager_signed_at)}`
                      : '—'}
                  </p>
                </div>
              </div>
              {selected.notes && (
                <div>
                  <Label>{t('contractsPage.cancelReason')}</Label>
                  <p className="whitespace-pre-wrap text-sm">{selected.notes}</p>
                </div>
              )}
              {/* E4: выбор согласованной редакции пункта для ЭТОГО договора (до подписания). */}
              <ContractWordingSection contract={selected} />
              <div className="flex flex-col gap-2">
                {/* Кнопка не ждёт готового файла: сервер сам ставит рендер и отвечает 202 (ARCH-03),
                    а `DocumentActions` опрашивает его по Retry-After. Пока условие требовало уже
                    существующий PDF, документ было НЕ ПОЛУЧИТЬ именно тогда, когда он ещё не
                    отрисован (аудит UI, U3). */}
                <DocumentActions
                  request={() => ({ path: `crm/contracts/${selected.id}/download-pdf/` })}
                  filenameBase={`RailTech_Contract_${selected.id}`}
                  size="default"
                />
                {selected.signed_file_url && (
                  <Button variant="outline" onClick={() => onDownloadSigned(selected)}>
                    <Download className="mr-2 h-4 w-4" />
                    {t('contractsPage.downloadSigned')}
                  </Button>
                )}
                {selected.invoice_id ? (
                  // An invoice already exists for this contract — route to it instead
                  // of re-creating. Falls back to "Create invoice" once it's cancelled
                  // (server sets invoice_id back to null).
                  <Button
                    variant="outline"
                    onClick={() => { window.location.hash = 'invoices'; }}
                  >
                    <Receipt className="mr-2 h-4 w-4" />
                    {t('contractsPage.openInvoice')}
                  </Button>
                ) : selected.status === 'SIGNED' && (
                  <Button
                    variant="outline"
                    onClick={() => onCreateInvoice(selected)}
                    disabled={generateInvoice.isPending || isViewer}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <Receipt className="mr-2 h-4 w-4" />
                    {t('contractsPage.createInvoice')}
                  </Button>
                )}
                {selected.viewer_can_sign_client && !selected.client_signed_at && (selected.status === 'PENDING_CLIENT' || selected.status === 'DRAFT') && (
                  <Button
                    onClick={() => onSignClient(selected)}
                    disabled={signClient.isPending || isViewer}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <PenLine className="mr-2 h-4 w-4" />
                    {t('contractsPage.signClient')}
                  </Button>
                )}
                {selected.viewer_can_sign_manager && !selected.manager_signed_at && (selected.status === 'PENDING_MANAGER' || selected.status === 'PENDING_CLIENT' || selected.status === 'DRAFT') && (
                  <Button
                    onClick={() => onSignManager(selected)}
                    disabled={signManager.isPending || isViewer}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <PenLine className="mr-2 h-4 w-4" />
                    {t('contractsPage.signManager')}
                  </Button>
                )}
                <label
                  className={`flex items-center justify-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-sm ${isViewer ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:bg-accent'}`}
                  title={isViewer ? viewerTip : undefined}
                >
                  <Upload className="h-4 w-4" />
                  <span>{t('contractsPage.uploadSigned')}</span>
                  <input
                    type="file"
                    className="hidden"
                    accept=".pdf,.jpg,.jpeg,.png"
                    disabled={isViewer}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) onUploadFile(selected, f);
                    }}
                  />
                </label>
                <DocumentCheck contractId={selected.id} />
                {selected.status !== 'CANCELLED' && selected.status !== 'SIGNED' && (
                  <Button
                    variant="destructive"
                    onClick={() => setCancelTarget(selected)}
                    disabled={isViewer}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <Ban className="mr-2 h-4 w-4" />
                    {t('contractsPage.cancel')}
                  </Button>
                )}
                {isPlatformAdmin && selected.status !== 'CANCELLED' && (
                  <Button
                    variant="outline"
                    className="border-warning text-warning hover:bg-warning/10"
                    onClick={() => setForceCancelTarget(selected)}
                  >
                    <ShieldAlert className="mr-2 h-4 w-4" />
                    {t('contractsPage.forceCancel')}
                  </Button>
                )}
              </div>
            </div>
            <SheetFooter />
          </SheetContent>
        </Sheet>
      )}

      <AlertDialog open={!!cancelTarget} onOpenChange={(o) => !o && setCancelTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('contractsPage.confirmCancel')}</AlertDialogTitle>
            <AlertDialogDescription>{cancelTarget?.number}</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <Label htmlFor="cancelReason">{t('contractsPage.cancelReason')}</Label>
            <Textarea
              id="cancelReason"
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onCancel} disabled={cancelMut.isPending}>
              {t('contractsPage.cancel')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={!!forceCancelTarget}
        onOpenChange={(o) => { if (!o) { setForceCancelTarget(null); setForceCancelReason(''); } }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2 text-warning">
              <ShieldAlert className="h-4 w-4" />
              {t('contractsPage.confirmForceCancel')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t('contractsPage.forceCancelHint', { number: forceCancelTarget?.number })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <Label htmlFor="forceCancelReason">{t('contractsPage.forceCancelReason')}</Label>
            <Textarea
              id="forceCancelReason"
              value={forceCancelReason}
              onChange={(e) => setForceCancelReason(e.target.value)}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onForceCancel} disabled={forceCancelMut.isPending}>
              {t('contractsPage.forceCancel')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}

export default ContractsPage;
