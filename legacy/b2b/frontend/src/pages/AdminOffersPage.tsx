import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Tags, Pencil, Trash2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import {
  useOffers, useCreateOffer, useUpdateOffer, useDeleteOffer,
  useProducts, useStockStatuses,
} from '@/hooks/useCatalog';
import { useCurrencies, useDeliveryBases } from '@/hooks/useMasterData';
import { useCompanies } from '@/hooks/useAccounts';
import type { SupplierOffer } from '@/api/catalogApi';

type Draft = Partial<SupplierOffer>;

function OfferFormSheet({
  open, onOpenChange, target,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  target: SupplierOffer | null;
}) {
  const { t } = useTranslation();
  const createMut = useCreateOffer();
  const updateMut = useUpdateOffer();
  const { data: products } = useProducts({ fetchAll: true });
  // Supplier picker: only SUPPLIER-type companies (compared by CODE), and the full
  // list — not the first 20 (M2). A SupplierOffer's supplier must be a seller company.
  const { data: companies } = useCompanies({ 'types__code': 'SUPPLIER', fetchAll: true });
  const { data: currencies } = useCurrencies();
  const { data: deliveryBases } = useDeliveryBases();
  const { data: stockStatuses } = useStockStatuses();

  const [draft, setDraft] = useState<Draft>(() => target ?? { is_active: true, min_order_qty: 1 });
  useMemo(() => setDraft(target ?? { is_active: true, min_order_qty: 1 }), [target]);

  const busy = createMut.isPending || updateMut.isPending;
  const isEdit = Boolean(target?.id);

  const update = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const submit = async () => {
    if (!draft.supplier || !draft.base_price) {
      toast.error(t('adminOffers.missingFields'));
      return;
    }
    const payload: Partial<SupplierOffer> = {
      supplier: Number(draft.supplier),
      supplier_sku: draft.supplier_sku ?? '',
      base_price: String(draft.base_price),
      currency: draft.currency ? Number(draft.currency) : null,
      delivery_basis: draft.delivery_basis ? Number(draft.delivery_basis) : null,
      stock_status: draft.stock_status ? Number(draft.stock_status) : null,
      delivery_lead_time: draft.delivery_lead_time ?? '',
      stock_quantity: Number(draft.stock_quantity ?? 0),
      in_stock_lead_time_days: Number(draft.in_stock_lead_time_days ?? 0),
      order_lead_time_days: Number(draft.order_lead_time_days ?? 0),
      min_order_qty: draft.min_order_qty ?? 1,
      is_active: draft.is_active ?? true,
    };
    // product is immutable after create
    if (!isEdit && draft.product) {
      payload.product = Number(draft.product);
    }
    try {
      if (isEdit && target) {
        await updateMut.mutateAsync({ id: target.id, data: payload });
        toast.success(t('adminOffers.updated'));
      } else {
        await createMut.mutateAsync(payload);
        toast.success(t('adminOffers.created'));
      }
      onOpenChange(false);
    } catch {
      toast.error(t('adminOffers.saveFailed'));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{isEdit ? t('adminOffers.edit') : t('adminOffers.new')}</SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-4 px-4">
          {!isEdit && (
            <div className="space-y-2">
              <Label>{t('adminOffers.fields.product')}</Label>
              <Select
                value={draft.product ? String(draft.product) : undefined}
                onValueChange={(v) => update({ product: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(products ?? []).map((p) => (
                    <SelectItem key={p.id} value={String(p.id)}>{p.name} {p.sku ? `(${p.sku})` : ''}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="space-y-2">
            <Label>{t('adminOffers.fields.supplier')}</Label>
            <Select
              value={draft.supplier ? String(draft.supplier) : undefined}
              onValueChange={(v) => update({ supplier: Number(v) })}
            >
              <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
              <SelectContent>
                {(companies ?? []).map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>{t('adminOffers.fields.supplierSku')}</Label>
            <Input value={draft.supplier_sku ?? ''} onChange={(e) => update({ supplier_sku: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('adminOffers.fields.basePrice')}</Label>
              <Input
                type="number"
                step="0.01"
                value={draft.base_price ?? ''}
                onChange={(e) => update({ base_price: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>{t('adminOffers.fields.currency')}</Label>
              <Select
                value={draft.currency ? String(draft.currency) : undefined}
                onValueChange={(v) => update({ currency: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(currencies ?? []).map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>{c.code}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('adminOffers.fields.deliveryBasis')}</Label>
              <Select
                value={draft.delivery_basis ? String(draft.delivery_basis) : undefined}
                onValueChange={(v) => update({ delivery_basis: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(deliveryBases ?? []).map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.code}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t('adminOffers.fields.stockStatus')}</Label>
              <Select
                value={draft.stock_status ? String(draft.stock_status) : undefined}
                onValueChange={(v) => update({ stock_status: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(stockStatuses ?? []).map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('adminOffers.fields.leadTime')}</Label>
              <Input value={draft.delivery_lead_time ?? ''} onChange={(e) => update({ delivery_lead_time: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label>{t('adminOffers.fields.minQty')}</Label>
              <Input
                type="number"
                value={draft.min_order_qty ?? 1}
                onChange={(e) => update({ min_order_qty: Number(e.target.value) })}
              />
            </div>
          </div>
          <div className="space-y-1">
            <Label className="text-base">{t('adminOffers.availability.title')}</Label>
            <p className="text-xs text-muted-foreground">{t('adminOffers.availability.hint')}</p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('adminOffers.fields.stockQuantity')}</Label>
              <Input
                type="number"
                min="0"
                step="1"
                value={draft.stock_quantity ?? 0}
                onChange={(e) => update({ stock_quantity: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label>{t('adminOffers.fields.inStockLeadTimeDays')}</Label>
              <Input
                type="number"
                min="0"
                step="1"
                value={draft.in_stock_lead_time_days ?? 0}
                onChange={(e) => update({ in_stock_lead_time_days: Number(e.target.value) })}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>{t('adminOffers.fields.orderLeadTimeDays')}</Label>
            <Input
              type="number"
              min="0"
              step="1"
              value={draft.order_lead_time_days ?? 0}
              onChange={(e) => update({ order_lead_time_days: Number(e.target.value) })}
            />
          </div>
        </div>

        <SheetFooter className="mt-6">
          <Button onClick={submit} disabled={busy} className="w-full">
            {isEdit ? t('adminOffers.save') : t('adminOffers.create')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export function AdminOffersPage() {
  const { t } = useTranslation();
  // Fetch the complete sets (DRF pages at 20) so search/sort/Pager + stat tiles are
  // accurate and every offer's product/stock label resolves (H4 / M1).
  const { data: offers, isLoading, isError, refetch } = useOffers({ fetchAll: true });
  const { data: products } = useProducts({ fetchAll: true });
  const { data: stockStatuses } = useStockStatuses();
  const deleteMut = useDeleteOffer();

  const listParams = useListParams(['active'] as const, { defaultOrdering: '-created_at' });
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<SupplierOffer | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SupplierOffer | null>(null);

  const productNameById = useMemo(() => {
    const productMap = new Map<number, string>();
    (products ?? []).forEach((p) => productMap.set(p.id, `${p.name}${p.sku ? ' · ' + p.sku : ''}`));
    return productMap;
  }, [products]);

  // The offer serializer returns stock_status as a raw FK id; resolve it to a label
  // via the lookup table (M1 — table previously showed the int).
  const stockNameById = useMemo(() => {
    const stockMap = new Map<number, string>();
    (stockStatuses ?? []).forEach((s) => stockMap.set(s.id, s.name));
    return stockMap;
  }, [stockStatuses]);

  const onEdit = (o: SupplierOffer) => {
    setEditTarget(o);
    setSheetOpen(true);
  };
  const onNew = () => {
    setEditTarget(null);
    setSheetOpen(true);
  };
  const onDelete = async () => {
    if (!deleteTarget) return;
    await deleteMut.mutateAsync(deleteTarget.id);
    toast.success(t('adminOffers.deleted'));
  };

  const stats = [
    { label: t('adminOffers.stats.total'), value: String(offers?.length ?? '—') },
    { label: t('adminOffers.stats.active'), value: String(offers?.filter((o) => o.is_active).length ?? '—') },
  ];

  return (
    <PageShell
      title={t('adminOffers.title')}
      description={t('adminOffers.description')}
      icon={<Tags className="h-5 w-5" />}
      stats={stats}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        filters={[
          {
            key: 'active',
            value: listParams.filters.active,
            onChange: (v) => listParams.setFilter('active', v),
            allLabel: t('adminOffers.allActive'),
            options: [
              { value: 'yes', label: t('adminOffers.yes') },
              { value: 'no', label: t('adminOffers.no') },
            ],
          },
        ]}
        newLabel={t('adminOffers.new')}
        onNew={onNew}
      />

      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(offers ?? [], listParams, {
              searchFields: (o) => [
                o.supplier_data?.name,
                o.product ? productNameById.get(o.product) : '',
                o.supplier_sku,
                o.base_price,
              ],
              filterPredicates: {
                active: (o, v) => (v === 'yes' ? !!o.is_active : !o.is_active),
              },
              sortAccessors: {
                product: (o) => o.product ? productNameById.get(o.product) ?? '' : '',
                supplier: (o) => o.supplier_data?.name ?? '',
                price: (o) => Number(o.base_price) || 0,
              },
            });
            if (isLoading) return <LoadingRows rows={5} />;
            if (isError) return <ErrorState onRetry={() => refetch()} />;
            if (!pageItems.length) return <EmptyState icon={<Tags className="h-5 w-5" />} message={t('adminOffers.emptyState')} />;
            return (
            <>
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead sortKey="product" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminOffers.table.product')}</SortableHead>
                  <SortableHead sortKey="supplier" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminOffers.table.supplier')}</SortableHead>
                  <SortableHead sortKey="price" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminOffers.table.price')}</SortableHead>
                  <TableHead>{t('adminOffers.table.status')}</TableHead>
                  <TableHead>{t('adminOffers.table.active')}</TableHead>
                  <TableHead className="text-right">{t('adminOffers.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((o) => (
                  <TableRow key={o.id}>
                    <TableCell className="text-sm">
                      {o.product ? productNameById.get(o.product) ?? '—' : '—'}
                    </TableCell>
                    <TableCell className="text-sm">{o.supplier_data?.name ?? '—'}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {o.base_price} {o.currency_data?.code ?? ''}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {o.stock_status ? stockNameById.get(o.stock_status) ?? '—' : '—'}
                    </TableCell>
                    <TableCell>
                      <Badge variant={o.is_active ? 'default' : 'secondary'}>
                        {o.is_active ? t('adminOffers.yes') : t('adminOffers.no')}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => onEdit(o)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(o)}>
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </div>
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

      <OfferFormSheet open={sheetOpen} onOpenChange={setSheetOpen} target={editTarget} />

      <ConfirmActionDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={t('adminOffers.confirmDelete')}
        description={t('adminOffers.confirmDeleteDesc')}
        variant="destructive"
        confirmLabel={t('adminOffers.delete')}
        cancelLabel={t('adminOffers.cancel')}
        onConfirm={onDelete}
      />
    </PageShell>
  );
}

export default AdminOffersPage;
