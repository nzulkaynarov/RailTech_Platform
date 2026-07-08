import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { FileText, PenLine, Upload, Ban, FileSignature, ShieldAlert } from 'lucide-react';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { ManualModeBanner } from '@/components/Shared/ManualModeBanner';
import {
  Toolbar, SortableHead, Pager, useListParams, applyListParams,
} from '@/components/DataTable';
import {
  useContracts, useSignContractClient, useSignContractManager,
  useUploadSignedContract, useCancelContract, useForceCancelContract,
} from '@/hooks/useBilling';
import { useUserStore } from '@/store/userStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import type { Contract, ContractStatus } from '@/api/contractsApi';
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
  const [cancelReason, setCancelReason] = useState('');
  const [forceCancelTarget, setForceCancelTarget] = useState<Contract | null>(null);
  const [forceCancelReason, setForceCancelReason] = useState('');

  const role = useUserStore((s) => s.role);
  const activeStatus = useUserStore((s) => s.activeStatus);
  const isPlatformAdmin = role === 'ADMIN';
  // Contract is double-signed: the buyer signs as client, the seller as manager.
  const isBuyer = activeStatus === 'BUYER';
  const isSeller = !isBuyer; // SELLER / MANUFACTURER context
  const isViewer = useIsViewerMode();
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');
  const { data: contracts, isLoading, isError, refetch } = useContracts(undefined);
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
  // Side indicator (P0-1): which side WE act as on these contracts. Derived from the
  // page context (activeStatus) — the same signal that already gates the sign buttons.
  // The Contract response carries no buyer/seller company id, so a truthful
  // per-contract side would need a serializer field (reported in CROSS-WP).
  const viewerSide: 'buyer' | 'seller' = isBuyer ? 'buyer' : 'seller';
  const sideBadge = (
    <Badge
      variant="outline"
      data-side={viewerSide}
      className={isBuyer ? 'border-info text-info' : 'border-primary text-primary'}
    >
      {t(`contractsPage.side.${viewerSide}`)}
    </Badge>
  );

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

      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(contracts ?? [], listParams, {
              searchFields: (c) => [c.number, String(c.deal)],
              filterPredicates: {
                status: (c, v) => c.status === v,
              },
              sortAccessors: {
                number: (c) => c.number,
                deal: (c) => c.deal,
                total: (c) => Number(c.total_amount),
                status: (c) => c.status,
                created_at: (c) => c.created_at,
              },
            });
            if (isLoading) return <LoadingRows rows={6} />;
            if (isError) return <ErrorState onRetry={refetch} />;
            if (!pageItems.length) {
              return (
                <EmptyState
                  icon={<FileSignature className="h-5 w-5" />}
                  message={t('contractsPage.emptyState')}
                  hint={t('contractsPage.emptyStateHint')}
                />
              );
            }
            return (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead sortKey="number" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('contractsPage.table.number')}
                      </SortableHead>
                      <SortableHead sortKey="deal" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('contractsPage.table.deal')}
                      </SortableHead>
                      <TableHead>{t('contractsPage.table.side')}</TableHead>
                      <SortableHead sortKey="total" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('contractsPage.table.total')}
                      </SortableHead>
                      <SortableHead sortKey="status" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('contractsPage.table.status')}
                      </SortableHead>
                      <SortableHead sortKey="created_at" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('contractsPage.table.created')}
                      </SortableHead>
                      <TableHead className="text-right">{t('contractsPage.table.actions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pageItems.map((c) => (
                      <TableRow
                        key={c.id}
                        role="button"
                        tabIndex={0}
                        aria-label={`${t('common.open')} ${c.number}`}
                        className="cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
                        onClick={(event) => {
                          // Ignore clicks that originate inside a row control (the action button
                          // and DealLink already open the panel / navigate themselves).
                          if ((event.target as HTMLElement).closest('[data-row-action]')) return;
                          setSelectedId(c.id);
                        }}
                        onKeyDown={(event) => {
                          // Only activate when the row itself is focused, not a nested control.
                          if (event.target !== event.currentTarget) return;
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            setSelectedId(c.id);
                          }
                        }}
                      >
                        <TableCell className="font-medium">{c.number}</TableCell>
                        <TableCell><DealLink dealId={c.deal} /></TableCell>
                        <TableCell>{sideBadge}</TableCell>
                        <TableCell className="tabular-nums">{formatCurrency(Number(c.total_amount))}</TableCell>
                        <TableCell>
                          <Badge variant={STATUS_VARIANT[c.status]}>
                            {t(`contractsPage.status.${c.status}`)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {new Date(c.created_at).toLocaleDateString()}
                        </TableCell>
                        <TableCell className="text-right" data-row-action>
                          <Button variant="ghost" size="sm" onClick={() => setSelectedId(c.id)}>
                            <FileText className="h-4 w-4" />
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
              <SheetDescription className="flex flex-wrap items-center gap-2">
                <Badge variant={STATUS_VARIANT[selected.status]}>
                  {t(`contractsPage.status.${selected.status}`)}
                </Badge>
                {sideBadge}
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
                      ? `${selected.client_signer_name} · ${new Date(selected.client_signed_at).toLocaleString()}`
                      : '—'}
                  </p>
                </div>
                <div>
                  <Label>{t('contractsPage.signManager')}</Label>
                  <p className="text-muted-foreground">
                    {selected.manager_signed_at
                      ? `${selected.manager_signer_name} · ${new Date(selected.manager_signed_at).toLocaleString()}`
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
              <div className="flex flex-col gap-2">
                {selected.pdf_url && (
                  <DocumentActions
                    request={() => ({ path: `crm/contracts/${selected.id}/download-pdf/` })}
                    filenameBase={`RailTech_Contract_${selected.id}`}
                    size="default"
                  />
                )}
                {isBuyer && !selected.client_signed_at && (selected.status === 'PENDING_CLIENT' || selected.status === 'DRAFT') && (
                  <Button
                    onClick={() => onSignClient(selected)}
                    disabled={signClient.isPending || isViewer}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <PenLine className="mr-2 h-4 w-4" />
                    {t('contractsPage.signClient')}
                  </Button>
                )}
                {isSeller && !selected.manager_signed_at && (selected.status === 'PENDING_MANAGER' || selected.status === 'PENDING_CLIENT' || selected.status === 'DRAFT') && (
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
