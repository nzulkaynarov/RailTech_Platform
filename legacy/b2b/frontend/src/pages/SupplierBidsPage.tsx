import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { Gavel, Check, X } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import { SupplierBidSubmitDialog } from '@/components/CRM/SupplierBidSubmitDialog';
import { useSupplierBids, useAcceptBid, useRejectBid } from '@/hooks/useBidding';
import { useUserStore } from '@/store/userStore';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import type { SupplierBid, SupplierBidStatus } from '@/api/biddingApi';

const STATUS_VARIANT: Record<SupplierBidStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  DRAFT: 'secondary',
  SUBMITTED: 'outline',
  ACCEPTED: 'default',
  REJECTED: 'destructive',
  WITHDRAWN: 'secondary',
};
const STATUS_CODES: SupplierBidStatus[] = ['DRAFT', 'SUBMITTED', 'ACCEPTED', 'REJECTED', 'WITHDRAWN'];

interface SupplierBidsPageProps {
  onNavigate?: (target: string) => void;
}

export function SupplierBidsPage({ onNavigate }: SupplierBidsPageProps = {}) {
  const { t } = useTranslation();
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [selected, setSelected] = useState<SupplierBid | null>(null);
  const [rejectTarget, setRejectTarget] = useState<SupplierBid | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [submitOpen, setSubmitOpen] = useState(false);
  const [submitDealId, setSubmitDealId] = useState('');
  const activeStatus = useUserStore((s) => s.activeStatus);
  const isSupplier = activeStatus === 'SELLER' || activeStatus === 'MANUFACTURER';
  // Supplier id comes from auth store (primary_company.id). Fallback: let backend resolve.
  const supplierCompanyId = useUserStore((s) => (s.company as { id?: number } | undefined)?.id ?? null);

  const queryParams = statusFilter !== 'all' ? { status: statusFilter } : undefined;
  const { data: bids, isLoading } = useSupplierBids(queryParams);
  const acceptMut = useAcceptBid();
  const rejectMut = useRejectBid();
  const isViewer = useIsViewerMode();
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');

  const stats = useMemo(() => {
    const list = bids ?? [];
    return [
      { label: t('supplierBidsPage.stats.total'), value: String(list.length) },
      { label: t('supplierBidsPage.stats.submitted'), value: String(list.filter((b) => b.status === 'SUBMITTED').length) },
      { label: t('supplierBidsPage.stats.accepted'), value: String(list.filter((b) => b.status === 'ACCEPTED').length) },
    ];
  }, [bids, t]);

  const onAccept = async (b: SupplierBid) => {
    try {
      await acceptMut.mutateAsync(b.id);
      toast.success(t('supplierBidsPage.accepted'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onReject = async () => {
    if (!rejectTarget) return;
    try {
      await rejectMut.mutateAsync({ id: rejectTarget.id, reason: rejectReason });
      toast.success(t('supplierBidsPage.rejected'));
      setRejectTarget(null);
      setRejectReason('');
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <PageShell
      title={t('supplierBidsPage.title')}
      description={t('supplierBidsPage.description')}
      icon={<Gavel className="h-5 w-5" />}
      stats={stats}
    >
      <Card>
        <CardContent className="flex flex-col gap-4 p-4">
          {isSupplier && (
            <div className="flex flex-wrap items-end gap-2">
              <div>
                <Label htmlFor="bid-deal-id">{t('supplierBidsPage.table.deal')}</Label>
                <input
                  id="bid-deal-id"
                  type="number"
                  className="mt-1 block w-32 rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={submitDealId}
                  onChange={(e) => setSubmitDealId(e.target.value)}
                />
              </div>
              <Button
                size="sm"
                disabled={!submitDealId || isViewer}
                title={isViewer ? viewerTip : undefined}
                onClick={() => setSubmitOpen(true)}
              >
                {t('supplierBidsPage.submit')}
              </Button>
            </div>
          )}
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-52"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('supplierBidsPage.allStatuses')}</SelectItem>
              {STATUS_CODES.map((s) => (
                <SelectItem key={s} value={s}>{t(`supplierBidsPage.status.${s}`)}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {isLoading ? <LoadingRows rows={6} /> : (bids?.length ?? 0) === 0 ? (
            <EmptyState
              icon={<Gavel className="h-5 w-5" />}
              message={t('supplierBidsPage.emptyState')}
              hint={isSupplier ? t('supplierBidsPage.emptyStateSupplierHint') : t('supplierBidsPage.emptyStateBuyerHint')}
              action={!isSupplier && onNavigate ? {
                label: t('supplierBidsPage.goToDeals'),
                onClick: () => onNavigate('crm-deals'),
              } : undefined}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('supplierBidsPage.table.deal')}</TableHead>
                  <TableHead>{t('supplierBidsPage.table.supplier')}</TableHead>
                  <TableHead>{t('supplierBidsPage.table.total')}</TableHead>
                  <TableHead>{t('supplierBidsPage.table.leadTime')}</TableHead>
                  <TableHead>{t('supplierBidsPage.table.status')}</TableHead>
                  <TableHead>{t('supplierBidsPage.table.submittedAt')}</TableHead>
                  <TableHead className="text-right">{t('supplierBidsPage.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(bids ?? []).map((b) => (
                  <TableRow key={b.id}>
                    <TableCell>#{b.deal}</TableCell>
                    <TableCell>{b.supplier_name}</TableCell>
                    <TableCell className="tabular-nums">{b.total_amount}</TableCell>
                    <TableCell>{b.lead_time_days ?? '—'}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[b.status]}>
                        {t(`supplierBidsPage.status.${b.status}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {b.submitted_at ? new Date(b.submitted_at).toLocaleDateString() : '—'}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => setSelected(b)}>
                          <Gavel className="h-4 w-4" />
                        </Button>
                        {b.status === 'SUBMITTED' && (
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => onAccept(b)}
                              disabled={isViewer}
                              title={isViewer ? viewerTip : undefined}
                            >
                              <Check className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setRejectTarget(b)}
                              disabled={isViewer}
                              title={isViewer ? viewerTip : undefined}
                            >
                              <X className="h-4 w-4 text-destructive" />
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {selected && (
        <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
          <SheetContent className="overflow-y-auto sm:max-w-lg">
            <SheetHeader>
              <SheetTitle>{selected.supplier_name}</SheetTitle>
              <SheetDescription>
                <Badge variant={STATUS_VARIANT[selected.status]}>
                  {t(`supplierBidsPage.status.${selected.status}`)}
                </Badge>
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-4 p-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><Label>{t('supplierBidsPage.table.deal')}</Label><p>#{selected.deal}</p></div>
                <div><Label>{t('supplierBidsPage.table.total')}</Label><p className="tabular-nums">{selected.total_amount}</p></div>
                <div><Label>{t('supplierBidsPage.table.leadTime')}</Label><p>{selected.lead_time_days ?? '—'}</p></div>
              </div>
              {selected.notes && (
                <div>
                  <Label>{t('supplierBidsPage.table.submittedAt')}</Label>
                  <p className="whitespace-pre-wrap text-sm">{selected.notes}</p>
                </div>
              )}
              {selected.items.length > 0 && (
                <>
                  <Separator />
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>#</TableHead>
                        <TableHead>{t('supplierBidsPage.itemHeaders.description')}</TableHead>
                        <TableHead>{t('supplierBidsPage.itemHeaders.qty')}</TableHead>
                        <TableHead>{t('supplierBidsPage.itemHeaders.unit')}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {selected.items.map((it, idx) => (
                        <TableRow key={it.id}>
                          <TableCell>{idx + 1}</TableCell>
                          <TableCell>{it.description}</TableCell>
                          <TableCell>{it.quantity}</TableCell>
                          <TableCell className="tabular-nums">{it.unit_price}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </>
              )}
            </div>
          </SheetContent>
        </Sheet>
      )}

      {isSupplier && submitDealId && supplierCompanyId && (
        <SupplierBidSubmitDialog
          dealId={Number(submitDealId)}
          supplierId={supplierCompanyId}
          open={submitOpen}
          onOpenChange={setSubmitOpen}
        />
      )}

      <AlertDialog open={!!rejectTarget} onOpenChange={(o) => !o && setRejectTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('supplierBidsPage.reject')}</AlertDialogTitle>
            <AlertDialogDescription>{rejectTarget?.supplier_name}</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <Label htmlFor="rejectReason">{t('contractsPage.cancelReason')}</Label>
            <Textarea
              id="rejectReason"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onReject} disabled={rejectMut.isPending}>
              {t('supplierBidsPage.reject')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}

export default SupplierBidsPage;
