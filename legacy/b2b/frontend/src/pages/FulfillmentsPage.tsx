import { useMemo, useState } from 'react';
import { openableRowProps } from '@/lib/rowClick';
import { formatDate } from '@/lib/formatLocale';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { Truck } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import { useFulfillments, useUpdateFulfillmentStatus } from '@/hooks/useBilling';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { FulfillmentStatus as FStatusCode } from '@/lib/codes';
import type { Fulfillment, FulfillmentStatus } from '@/api/fulfillmentApi';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { DealLink } from '@/components/Shared/DealLink';

const STATUS_VARIANT: Record<FulfillmentStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  PENDING: 'secondary',
  SHIPPED: 'outline',
  IN_TRANSIT: 'outline',
  DELIVERED: 'outline',
  ACCEPTED: 'default',
  DISPUTED: 'destructive',
};
const STATUS_CODES: FulfillmentStatus[] = [
  'PENDING', 'SHIPPED', 'IN_TRANSIT', 'DELIVERED', 'ACCEPTED', 'DISPUTED',
];
/** Приёмку и спор подтверждает ЗАКАЗЧИК — сервер авторизует их по стороне покупателя. */
const BUYER_STATUS_CODES: FulfillmentStatus[] = [FStatusCode.ACCEPTED, FStatusCode.DISPUTED];

export function FulfillmentsPage() {
  const { t } = useTranslation();
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [confirm, setConfirm] = useState<{ f: Fulfillment; status: FulfillmentStatus } | null>(null);
  const [editing, setEditing] = useState<Fulfillment | null>(null);
  const [form, setForm] = useState({
    status: 'PENDING' as FulfillmentStatus,
    tracking_number: '',
    carrier: '',
    expected_delivery_date: '',
    notes: '',
  });

  const queryParams = statusFilter !== 'all' ? { status: statusFilter } : undefined;
  const { data: list, isLoading, isError, refetch } = useFulfillments(queryParams);
  const updateMut = useUpdateFulfillmentStatus();
  const isViewer = useIsViewerMode();
  // Продвигает отгрузку продавец, принимает/спорит покупатель — сторону по КАЖДОЙ строке
  // считает сервер (`viewer_can_ship` / `viewer_can_accept`). Прежний вывод из activeStatus
  // брал первый тип компании: посредник, который и покупает, и продаёт, терял половину
  // действий, а на своей же отгрузке видел чужой набор кнопок.
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');

  const stats = useMemo(() => {
    const items = list ?? [];
    return [
      { label: t('fulfillmentPage.stats.total'), value: String(items.length) },
      { label: t('fulfillmentPage.stats.inTransit'), value: String(items.filter((f) => f.status === 'IN_TRANSIT' || f.status === 'SHIPPED').length) },
      { label: t('fulfillmentPage.stats.accepted'), value: String(items.filter((f) => f.status === 'ACCEPTED').length) },
    ];
  }, [list, t]);

  const startEdit = (f: Fulfillment) => {
    setEditing(f);
    setForm({
      status: f.status,
      tracking_number: f.tracking_number,
      carrier: f.carrier,
      expected_delivery_date: f.expected_delivery_date ?? '',
      notes: f.notes,
    });
  };

  const submit = async () => {
    if (!editing) return;
    try {
      await updateMut.mutateAsync({
        deal_id: editing.deal,
        status: form.status,
        tracking_number: form.tracking_number || undefined,
        carrier: form.carrier || undefined,
        expected_delivery_date: form.expected_delivery_date || undefined,
        notes: form.notes || undefined,
      });
      toast.success(t('fulfillmentPage.statusUpdated'));
      setEditing(null);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  // Buyer-side one-click accept/dispute of a delivered shipment.
  const buyerAct = async (f: Fulfillment, status: FulfillmentStatus) => {
    try {
      await updateMut.mutateAsync({ deal_id: f.deal, status });
      toast.success(
        status === FStatusCode.ACCEPTED
          ? t('fulfillmentPage.acceptedToast')
          : status === FStatusCode.DISPUTED
            ? t('fulfillmentPage.disputedToast')
            : t('fulfillmentPage.statusUpdated'),
      );
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <PageShell
      title={t('fulfillmentPage.title')}
      description={t('fulfillmentPage.description')}
      icon={<Truck className="h-5 w-5" />}
      stats={stats}
      statsError={isError}
    >
      <Card>
        <CardContent className="flex flex-col gap-4 p-4">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-52"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('fulfillmentPage.allStatuses')}</SelectItem>
              {STATUS_CODES.map((s) => (
                <SelectItem key={s} value={s}>{t(`fulfillmentPage.status.${s}`)}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {isLoading ? <LoadingRows rows={6} /> : isError ? <ErrorState onRetry={refetch} /> : (list?.length ?? 0) === 0 ? (
            <EmptyState icon={<Truck className="h-5 w-5" />} message={t('fulfillmentPage.emptyState')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('fulfillmentPage.table.deal')}</TableHead>
                  <TableHead>{t('fulfillmentPage.table.status')}</TableHead>
                  <TableHead>{t('fulfillmentPage.table.expected')}</TableHead>
                  <TableHead>{t('fulfillmentPage.table.tracking')}</TableHead>
                  <TableHead>{t('fulfillmentPage.table.carrier')}</TableHead>
                  <TableHead className="text-right">{t('fulfillmentPage.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(list ?? []).map((f) => (
                  <TableRow
                    key={f.id}
                    {...(f.viewer_can_ship && !isViewer
                      ? openableRowProps(() => startEdit(f), `${t('common.open')} #${f.deal}`)
                      : {})}
                  >
                    <TableCell><DealLink dealId={f.deal} /></TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[f.status]}>
                        {t(`fulfillmentPage.status.${f.status}`)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {f.expected_delivery_date ? formatDate(f.expected_delivery_date) : '—'}
                    </TableCell>
                    <TableCell>{f.tracking_number || '—'}</TableCell>
                    <TableCell>{f.carrier || '—'}</TableCell>
                    <TableCell className="text-right" data-row-action>
                      {/* D2b: накладная — печатный артефакт отгрузки (Odoo Delivery Slip). */}
                      {f.shipped_at && (
                        <DocumentActions
                          request={() => ({ path: `crm/fulfillments/${f.id}/download-note/` })}
                          filenameBase={`RailTech_DeliveryNote_DN-${f.id}`}
                          size="sm"
                        />
                      )}
                      {f.viewer_can_ship && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => startEdit(f)}
                          disabled={isViewer}
                          title={isViewer ? viewerTip : undefined}
                        >
                          {t('fulfillmentPage.updateStatus')}
                        </Button>
                      )}
                      {/* Buyer accepts or disputes the delivery — ACCEPTED auto-closes
                          the deal (CLOSED_WON). Only once the seller marks DELIVERED. */}
                      {f.viewer_can_accept && f.status === FStatusCode.DELIVERED && (
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost" size="sm"
                            disabled={isViewer || updateMut.isPending}
                            title={isViewer ? viewerTip : undefined}
                            onClick={() => setConfirm({ f, status: FStatusCode.ACCEPTED })}
                          >
                            {t('fulfillmentPage.accept')}
                          </Button>
                          <Button
                            variant="ghost" size="sm"
                            disabled={isViewer || updateMut.isPending}
                            title={isViewer ? viewerTip : undefined}
                            onClick={() => setConfirm({ f, status: FStatusCode.DISPUTED })}
                          >
                            {t('fulfillmentPage.dispute')}
                          </Button>
                        </div>
                      )}
                      {/* After a dispute the buyer has no action — the conflict is
                          handled with the seller. Give a status hint + a way into
                          the deal chat instead of a silent dead-end. */}
                      {f.viewer_can_accept && f.status === FStatusCode.DISPUTED && (
                        <div className="flex flex-col items-end gap-1">
                          <span className="text-xs text-muted-foreground">{t('fulfillmentPage.disputedHint')}</span>
                          <DealLink dealId={f.deal} className="text-xs" />
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Sheet open={!!editing} onOpenChange={(o) => !o && setEditing(null)}>
        <SheetContent className="sm:max-w-md">
          <SheetHeader>
            <SheetTitle>{t('fulfillmentPage.updateStatus')}</SheetTitle>
          </SheetHeader>
          <div className="space-y-3 p-4">
            <div>
              <Label>{t('fulfillmentPage.form.status')}</Label>
              <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v as FulfillmentStatus })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {/* Шторка открывается ПРОДАВЦУ (`viewer_can_ship`), а список печатался
                      общий — вместе со статусами заказчика. Продавец выбирал «Принято»,
                      сервер отбивал, и витрина переводила общий код как «действие доступно
                      только членам компании»: он член своей компании, и отказ читался как
                      поломка. Покупателю приёмка и спор даны отдельными кнопками выше. */}
                  {STATUS_CODES.filter(
                    (s) => !BUYER_STATUS_CODES.includes(s) || editing?.viewer_can_accept,
                  ).map((s) => (
                    <SelectItem key={s} value={s}>{t(`fulfillmentPage.status.${s}`)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="trk">{t('fulfillmentPage.form.trackingNumber')}</Label>
              <Input id="trk" value={form.tracking_number}
                     onChange={(e) => setForm({ ...form, tracking_number: e.target.value })} />
            </div>
            <div>
              <Label htmlFor="carrier">{t('fulfillmentPage.form.carrier')}</Label>
              <Input id="carrier" value={form.carrier}
                     onChange={(e) => setForm({ ...form, carrier: e.target.value })} />
            </div>
            <div>
              <Label htmlFor="exp">{t('fulfillmentPage.form.expectedDeliveryDate')}</Label>
              <Input id="exp" type="date" value={form.expected_delivery_date}
                     onChange={(e) => setForm({ ...form, expected_delivery_date: e.target.value })} />
            </div>
            <div>
              <Label htmlFor="notes">{t('fulfillmentPage.form.notes')}</Label>
              <Textarea id="notes" value={form.notes}
                        onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>
          </div>
          <SheetFooter>
            <Button
              onClick={submit}
              disabled={updateMut.isPending || isViewer}
              title={isViewer ? viewerTip : undefined}
              className="w-full"
            >
              {t('fulfillmentPage.updateStatus')}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* Confirm the irreversible buyer decision — accepting closes the deal. */}
      <AlertDialog open={!!confirm} onOpenChange={(open) => { if (!open) setConfirm(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirm?.status === FStatusCode.DISPUTED ? t('fulfillmentPage.dispute') : t('fulfillmentPage.accept')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirm?.status === FStatusCode.DISPUTED
                ? t('fulfillmentPage.confirmDispute')
                : t('fulfillmentPage.confirmAccept')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className={confirm?.status === FStatusCode.DISPUTED ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90' : undefined}
              disabled={updateMut.isPending}
              onClick={() => { if (confirm) buyerAct(confirm.f, confirm.status); setConfirm(null); }}
            >
              {confirm?.status === FStatusCode.DISPUTED ? t('fulfillmentPage.dispute') : t('fulfillmentPage.accept')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}

export default FulfillmentsPage;
