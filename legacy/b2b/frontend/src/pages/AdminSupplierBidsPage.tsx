import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Gavel, Check, X, Eye } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { translateApiError } from '@/lib/apiError';
import { useSupplierBids, useAcceptBid, useRejectBid } from '@/hooks/useBidding';
import { AdminDataTable, useAdminTableQueryState } from '@/components/Admin/AdminDataTable';
import { AdminDetailLayout } from '@/components/Admin/AdminDetailLayout';
import { AdminActivityTimeline } from '@/components/Admin/AdminActivityTimeline';
import { ConfirmActionDialog } from '@/components/Admin/ConfirmActionDialog';
import { DetailKPIGrid } from '@/components/Admin/DetailKPIGrid';
import { PageShell } from './shared/PageShell';
import type { SupplierBid, SupplierBidStatus } from '@/api/biddingApi';

const STORAGE_KEY = 'adminBids';

const STATUS_VARIANT: Record<SupplierBidStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  DRAFT: 'secondary',
  SUBMITTED: 'outline',
  ACCEPTED: 'default',
  REJECTED: 'destructive',
  WITHDRAWN: 'secondary',
};

function BidDetailSheet({
  bid,
  open,
  onOpenChange,
}: {
  bid: SupplierBid | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { t } = useTranslation();
  if (!bid) return null;

  const overview = (
    <div className="space-y-4">
      <DetailKPIGrid
        columns={4}
        items={[
          {
            label: t('adminBids.table.status'),
            value: bid.status,
            tone:
              bid.status === 'ACCEPTED'
                ? 'success'
                : bid.status === 'REJECTED'
                  ? 'destructive'
                  : 'info',
          },
          { label: t('adminBids.table.total'), value: bid.total_amount },
          {
            label: t('adminBids.table.leadDays'),
            value: bid.lead_time_days != null ? String(bid.lead_time_days) : '—',
          },
          {
            label: t('adminBids.table.submittedAt'),
            value: bid.submitted_at ? new Date(bid.submitted_at).toLocaleString() : '—',
          },
        ]}
      />
      <div className="rounded-md border p-3 text-xs">
        <div className="mb-1 font-semibold">
          {t('adminBids.items')} ({bid.items.length})
        </div>
        <ul className="space-y-1">
          {bid.items.map((it) => (
            <li key={it.id} className="flex items-start justify-between gap-2">
              <span>
                {it.description || `item #${it.id}`} × {it.quantity}
              </span>
              <span className="tabular-nums">{it.unit_price}</span>
            </li>
          ))}
        </ul>
      </div>
      {bid.notes ? (
        <div className="rounded-md border p-3 text-xs">
          <div className="mb-1 font-semibold">{t('adminBids.notes')}</div>
          <div className="whitespace-pre-wrap">{bid.notes}</div>
        </div>
      ) : null}
    </div>
  );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col overflow-y-auto p-0 sm:max-w-2xl">
        <SheetHeader className="sr-only">
          <SheetTitle>
            {t('adminBids.detailTitle', { id: bid.id })}
          </SheetTitle>
        </SheetHeader>
        <div className="p-4 md:p-5">
          <AdminDetailLayout
            title={t('adminBids.detailTitle', { id: bid.id })}
            subtitle={bid.supplier_name}
            leading={
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
                <Gavel className="h-5 w-5" aria-hidden="true" />
              </div>
            }
            badges={[
              { label: bid.status, variant: STATUS_VARIANT[bid.status] },
            ]}
            tabs={[
              { id: 'overview', label: t('adminBids.detailTab.overview'), content: overview },
              {
                id: 'timeline',
                label: t('platformAdmin.activity.title'),
                content: <AdminActivityTimeline entityType="supplier_bid" entityId={bid.id} />,
              },
            ]}
          />
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function AdminSupplierBidsPage() {
  const { t } = useTranslation();
  const tableState = useAdminTableQueryState(STORAGE_KEY);
  const queryParams = useMemo(() => {
    const p: Record<string, string> = {};
    const tab = tableState.tab || 'all';
    if (tab !== 'all') p.status = tab;
    return Object.keys(p).length ? p : undefined;
  }, [tableState.tab]);
  const { data: allBids = [] } = useSupplierBids();
  const { data: bids = [], isLoading } = useSupplierBids(queryParams);
  const acceptMut = useAcceptBid();
  const rejectMut = useRejectBid();

  const [detail, setDetail] = useState<SupplierBid | null>(null);
  const [confirm, setConfirm] = useState<null | {
    kind: 'accept' | 'reject';
    bid: SupplierBid;
  }>(null);

  const counts = useMemo(
    () => ({
      all: allBids.length,
      SUBMITTED: allBids.filter((b) => b.status === 'SUBMITTED').length,
      ACCEPTED: allBids.filter((b) => b.status === 'ACCEPTED').length,
      REJECTED: allBids.filter((b) => b.status === 'REJECTED').length,
      DRAFT: allBids.filter((b) => b.status === 'DRAFT').length,
    }),
    [allBids],
  );

  async function runAccept(b: SupplierBid) {
    try {
      await acceptMut.mutateAsync(b.id);
      toast.success(t('adminBids.accepted'));
    } catch (e) {
      toast.error(translateApiError(e));
    } finally {
      setConfirm(null);
    }
  }

  async function runReject(b: SupplierBid, reason: string) {
    try {
      await rejectMut.mutateAsync({ id: b.id, reason });
      toast.success(t('adminBids.rejected'));
    } catch (e) {
      toast.error(translateApiError(e));
    } finally {
      setConfirm(null);
    }
  }

  return (
    <PageShell
      title={t('adminBids.title')}
      description={t('adminBids.description')}
      icon={<Gavel className="h-5 w-5" />}
      stats={[
        { label: t('adminBids.stats.total'), value: String(counts.all) },
        { label: t('adminBids.stats.submitted'), value: String(counts.SUBMITTED) },
        { label: t('adminBids.stats.accepted'), value: String(counts.ACCEPTED) },
        { label: t('adminBids.stats.rejected'), value: String(counts.REJECTED) },
      ]}
    >
      <AdminDataTable<SupplierBid>
        storageKey={STORAGE_KEY}
        rows={bids}
        getRowId={(b) => b.id}
        isLoading={isLoading}
        onRowClick={(b) => setDetail(b)}
        searchPlaceholder={t('adminBids.searchPlaceholder')}
        exportUrl={`${window.location.origin}/api/v1/crm/supplier-bids/export/`}
        tabs={[
          { id: 'all', label: t('common.all'), count: counts.all },
          { id: 'SUBMITTED', label: t('adminBids.stats.submitted'), count: counts.SUBMITTED },
          { id: 'ACCEPTED', label: t('adminBids.stats.accepted'), count: counts.ACCEPTED },
          { id: 'REJECTED', label: t('adminBids.stats.rejected'), count: counts.REJECTED },
          { id: 'DRAFT', label: 'DRAFT', count: counts.DRAFT },
        ]}
        columns={[
          {
            id: 'id',
            header: t('adminBids.table.id'),
            cell: (b) => <span className="font-mono tabular-nums">#{b.id}</span>,
            alwaysVisible: true,
          },
          {
            id: 'deal',
            header: t('adminBids.table.deal'),
            cell: (b) => (
              <span className="text-muted-foreground">#{b.deal}</span>
            ),
          },
          {
            id: 'supplier',
            header: t('adminBids.table.supplier'),
            cell: (b) => <span>{b.supplier_name}</span>,
          },
          {
            id: 'status',
            header: t('adminBids.table.status'),
            cell: (b) => <Badge variant={STATUS_VARIANT[b.status]}>{b.status}</Badge>,
          },
          {
            id: 'total',
            header: t('adminBids.table.total'),
            cell: (b) => <span className="tabular-nums">{b.total_amount}</span>,
          },
          {
            id: 'leadDays',
            header: t('adminBids.table.leadDays'),
            cell: (b) => (
              <span className="text-muted-foreground">{b.lead_time_days ?? '—'}</span>
            ),
          },
          {
            id: 'submitted_at',
            header: t('adminBids.table.submittedAt'),
            cell: (b) => (
              <span className="text-muted-foreground">
                {b.submitted_at ? new Date(b.submitted_at).toLocaleDateString() : '—'}
              </span>
            ),
          },
        ]}
        rowActions={[
          {
            id: 'view',
            label: t('common.open'),
            icon: <Eye className="h-3.5 w-3.5" />,
            onRun: (b) => setDetail(b),
          },
          {
            id: 'accept',
            label: t('adminBids.accept'),
            icon: <Check className="h-3.5 w-3.5 text-success" />,
            onRun: (b) => {
              if (b.status !== 'SUBMITTED') {
                toast.error(t('adminBids.notSubmitted'));
                return;
              }
              setConfirm({ kind: 'accept', bid: b });
            },
          },
          {
            id: 'reject',
            label: t('adminBids.reject'),
            icon: <X className="h-3.5 w-3.5 text-destructive" />,
            variant: 'destructive',
            onRun: (b) => {
              if (b.status !== 'SUBMITTED') {
                toast.error(t('adminBids.notSubmitted'));
                return;
              }
              setConfirm({ kind: 'reject', bid: b });
            },
          },
        ]}
        emptyIcon={<Gavel className="h-5 w-5 text-muted-foreground" />}
        emptyTitle={t('adminBids.empty')}
      />

      <ConfirmActionDialog
        open={confirm?.kind === 'accept'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title={t('adminBids.confirmAcceptTitle')}
        description={
          confirm?.kind === 'accept'
            ? t('adminBids.confirmAcceptDescription', {
                id: confirm.bid.id,
                supplier: confirm.bid.supplier_name,
              })
            : ''
        }
        confirmLabel={t('adminBids.accept')}
        variant="primary"
        onConfirm={() =>
          confirm?.kind === 'accept' ? runAccept(confirm.bid) : Promise.resolve()
        }
      />
      <ConfirmActionDialog
        open={confirm?.kind === 'reject'}
        onOpenChange={(v) => !v && setConfirm(null)}
        title={t('adminBids.confirmRejectTitle')}
        description={
          confirm?.kind === 'reject'
            ? t('adminBids.confirmRejectDescription', {
                id: confirm.bid.id,
                supplier: confirm.bid.supplier_name,
              })
            : ''
        }
        requireReason
        reasonTemplates={[
          t('adminBids.rejectTemplates.price'),
          t('adminBids.rejectTemplates.leadTime'),
          t('adminBids.rejectTemplates.other'),
        ]}
        confirmLabel={t('adminBids.reject')}
        variant="destructive"
        onConfirm={(p) =>
          confirm?.kind === 'reject' ? runReject(confirm.bid, p.reason) : Promise.resolve()
        }
      />

      <BidDetailSheet
        bid={detail}
        open={!!detail}
        onOpenChange={(v) => {
          if (!v) setDetail(null);
        }}
      />
    </PageShell>
  );
}

export default AdminSupplierBidsPage;
