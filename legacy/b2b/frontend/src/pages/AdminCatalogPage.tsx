import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Package, Pencil, Trash2, Send, Sparkles, Loader2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';
import { ConfirmActionDialog } from '@/components/Admin/ConfirmActionDialog';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import {
  useProducts, useProduct, useCreateProduct, useUpdateProduct, useDeleteProduct,
  useDomainTypes, useProductStatuses, useCategories, useManufacturers, useEquipmentGroups,
  useUploadProductImage, useDeleteProductImage,
  useUploadProductDocument, useDeleteProductDocument,
  useStockStatuses, useOffers, useCreateOffer, useUpdateOffer, useBulkPublishProducts,
  useEnrichProduct,
} from '@/hooks/useCatalog';
import { useUnits, useCurrencies, useDeliveryBases } from '@/hooks/useMasterData';
import { productStatusLabelKey } from '@/lib/codes';
import type { Product } from '@/api/catalogApi';
import { ImageGalleryUpload } from '@/components/Shared/ImageGalleryUpload';
import { FileUpload } from '@/components/Shared/FileUpload';

type Draft = Partial<Product> & { gost_drawing?: string | null; description?: string };

function emptyDraft(): Draft {
  return { name: '', description: '', gost_drawing: '' };
}

function ProductMediaSection({ productId }: { productId: number }) {
  const { t } = useTranslation();
  const { data: product } = useProduct(String(productId));
  const uploadImage = useUploadProductImage();
  const deleteImage = useDeleteProductImage();
  const uploadDoc = useUploadProductDocument();
  const deleteDoc = useDeleteProductDocument();

  const images = (product?.images ?? []).map(img => ({
    id: img.id,
    url: img.image ?? img.image_url,
    is_main: img.is_main,
  }));
  const docs = (product?.documents ?? []).map(doc => ({
    id: doc.id,
    name: doc.name,
    url: doc.file ?? doc.file_url,
  }));

  return (
    <div className="space-y-4">
      <div>
        <Label className="text-sm font-medium">{t('adminCatalog.media.images')}</Label>
        <ImageGalleryUpload
          images={images}
          onUpload={async (file, isMain) => {
            await uploadImage.mutateAsync({ productId, file, isMain });
          }}
          onRemove={async imageId => {
            await deleteImage.mutateAsync({ productId, imageId });
          }}
          className="mt-2"
        />
      </div>
      <div>
        <Label className="text-sm font-medium">{t('adminCatalog.media.documents')}</Label>
        <FileUpload
          className="mt-2"
          files={docs}
          onUpload={async file => {
            await uploadDoc.mutateAsync({ productId, file, name: file.name });
          }}
          onRemove={async docId => {
            await deleteDoc.mutateAsync({ productId, docId: Number(docId) });
          }}
          description={t('adminCatalog.media.documentsHelp')}
        />
      </div>
    </div>
  );
}

export function ProductFormSheet({
  open, onOpenChange, target, sellerCompanyId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  target: Product | null;
  // When set (seller context), show the pricing section and upsert the seller's own
  // SupplierOffer alongside the product. Admins manage offers on the dedicated page.
  sellerCompanyId?: number;
}) {
  const { t } = useTranslation();
  const { data: domainTypes } = useDomainTypes();
  const { data: statuses } = useProductStatuses();
  const { data: categories } = useCategories();
  const { data: units } = useUnits();
  const { data: manufacturers } = useManufacturers({ fetchAll: true });
  const { data: equipmentGroups } = useEquipmentGroups();
  const createMut = useCreateProduct();
  const updateMut = useUpdateProduct();

  // --- Seller pricing (H3) ---
  const sellerMode = Boolean(sellerCompanyId);
  const { data: currencies } = useCurrencies();
  const { data: stockStatuses } = useStockStatuses();
  const { data: deliveryBases } = useDeliveryBases();
  const createOfferMut = useCreateOffer();
  const updateOfferMut = useUpdateOffer();
  // On edit, the seller's own offer for this product (C2 scopes /offers/ to them).
  const { data: ownOffers } = useOffers(sellerMode && target?.id ? { product: target.id } : undefined);
  const ownOffer = sellerMode ? (ownOffers ?? []).find((o) => o.supplier === sellerCompanyId) ?? null : null;

  const [draft, setDraft] = useState<Draft>(() => target ?? emptyDraft());
  const [groupIds, setGroupIds] = useState<number[]>(() => target?.equipment_groups?.map((g) => g.id) ?? []);
  type OfferDraft = { base_price?: string; currency?: number | null; stock_status?: number | null; delivery_basis?: number | null; supplier_sku?: string };
  const [offerDraft, setOfferDraft] = useState<OfferDraft>({});

  useEffect(() => {
    setDraft(target ? { ...target } : emptyDraft());
    setGroupIds(target?.equipment_groups?.map((g) => g.id) ?? []);
  }, [target]);

  useEffect(() => {
    setOfferDraft(ownOffer
      ? {
          base_price: ownOffer.base_price,
          currency: ownOffer.currency ?? null,
          stock_status: ownOffer.stock_status ?? null,
          delivery_basis: ownOffer.delivery_basis ?? null,
          supplier_sku: ownOffer.supplier_sku ?? '',
        }
      : {});
  }, [ownOffer]);

  const updateOffer = (patch: Partial<OfferDraft>) => setOfferDraft((d) => ({ ...d, ...patch }));
  const busy = createMut.isPending || updateMut.isPending || createOfferMut.isPending || updateOfferMut.isPending;
  const isEdit = Boolean(target?.id);

  // Equipment groups are a RAILWAY_MACHINERY taxonomy and are required for that
  // domain (Product.clean()). Resolve the selected domain's code to gate the field.
  const domainCode = (domainTypes ?? []).find((d) => d.id === Number(draft.domain_type))?.code
    ?? (typeof draft.domain_type === 'string' ? draft.domain_type : undefined);
  const isRailway = domainCode === 'RAILWAY_MACHINERY';
  const toggleGroup = (id: number) =>
    setGroupIds((ids) => (ids.includes(id) ? ids.filter((g) => g !== id) : [...ids, id]));

  const update = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  // --- AI #2: enrich (suggestion only, seller reviews & edits) ---
  const enrichMut = useEnrichProduct();
  // Category hint is advisory text — the seller still picks the real category from
  // the DB dropdown (Rule 1: we never resolve/invent a Category id from the hint).
  const [categoryHint, setCategoryHint] = useState<string>('');

  const runEnrich = async () => {
    const name = draft.name?.trim();
    if (!name) {
      toast.error(t('adminCatalog.nameRequired'));
      return;
    }
    try {
      const suggestion = await enrichMut.mutateAsync({
        name,
        domain_code: domainCode,
        mpn: draft.manufacturer_part_number ?? undefined,
        gost: draft.gost_drawing ?? undefined,
      });
      // Empty object → AI disabled or nothing to suggest.
      if (!suggestion || Object.keys(suggestion).length === 0) {
        toast.info(t('adminCatalog.aiEnrich.empty'));
        return;
      }
      const patch: Partial<Draft> = {};
      if (suggestion.description) patch.description = suggestion.description;
      if (suggestion.specifications?.length) {
        // Map [{key,value}] → the Product.specifications JSON object the form persists.
        const specs: Record<string, string> = {};
        for (const spec of suggestion.specifications) {
          if (spec.key) specs[spec.key] = spec.value;
        }
        patch.specifications = specs;
      }
      update(patch);
      setCategoryHint(suggestion.suggested_category_hint ?? '');
      toast.success(t('adminCatalog.aiEnrich.applied'));
    } catch {
      toast.error(t('adminCatalog.aiEnrich.failed'));
    }
  };

  const submit = async () => {
    if (!draft.name?.trim()) {
      toast.error(t('adminCatalog.nameRequired'));
      return;
    }
    if (isRailway && groupIds.length === 0) {
      toast.error(t('adminCatalog.equipmentGroupsRequired'));
      return;
    }
    // brand (catalog.Manufacturer) replaces the deprecated manufacturer Company FK.
    // equipment_groups is an M2M write (list of ids) — the read type is
    // EquipmentGroup[], so the body goes through a write-shaped cast.
    const payload = {
      name: draft.name,
      description: draft.description || '',
      domain_type: draft.domain_type ? Number(draft.domain_type) : undefined,
      status: draft.status ? Number(draft.status) : undefined,
      category: draft.category ? Number(draft.category) : null,
      uom: draft.uom ? Number(draft.uom) : null,
      brand: draft.brand ? Number(draft.brand) : null,
      manufacturer_part_number: draft.manufacturer_part_number || '',
      equipment_groups: groupIds,
      gost_drawing: draft.gost_drawing || '',
      specifications: draft.specifications ?? undefined,
    } as unknown as Partial<Product>;
    try {
      let productId = target?.id;
      if (isEdit && target) {
        await updateMut.mutateAsync({ id: target.id, data: payload });
      } else {
        const created = await createMut.mutateAsync(payload);
        productId = created.id;
      }
      // Seller pricing (H3): upsert the seller's own offer for this product. Skipped
      // when no price is entered so a product can still be saved without an offer.
      if (sellerMode && productId && String(offerDraft.base_price ?? '').trim()) {
        const offerPayload = {
          product: productId,
          supplier: sellerCompanyId,
          base_price: String(offerDraft.base_price),
          currency: offerDraft.currency ? Number(offerDraft.currency) : null,
          stock_status: offerDraft.stock_status ? Number(offerDraft.stock_status) : null,
          delivery_basis: offerDraft.delivery_basis ? Number(offerDraft.delivery_basis) : null,
          supplier_sku: offerDraft.supplier_sku ?? '',
        };
        if (ownOffer) {
          await updateOfferMut.mutateAsync({ id: ownOffer.id, data: offerPayload });
        } else {
          await createOfferMut.mutateAsync(offerPayload);
        }
      }
      toast.success(isEdit ? t('adminCatalog.updated') : t('adminCatalog.created'));
      onOpenChange(false);
    } catch {
      toast.error(t('adminCatalog.saveFailed'));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{isEdit ? t('adminCatalog.editProduct') : t('adminCatalog.newProduct')}</SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-4 px-4">
          <div className="space-y-2">
            <Label>{t('adminCatalog.fields.name')}</Label>
            <Input value={draft.name ?? ''} onChange={(e) => update({ name: e.target.value })} />
          </div>

          <div className="flex items-start justify-between gap-3 rounded-md border border-dashed bg-muted/40 p-3">
            <div className="space-y-0.5">
              <p className="text-sm font-medium">{t('adminCatalog.aiEnrich.title')}</p>
              <p className="text-xs text-muted-foreground">{t('adminCatalog.aiEnrich.hint')}</p>
            </div>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={runEnrich}
              disabled={enrichMut.isPending || !draft.name?.trim()}
              className="shrink-0"
            >
              {enrichMut.isPending
                ? <Loader2 className="size-4 animate-spin" />
                : <Sparkles className="size-4" />}
              {t('adminCatalog.aiEnrich.button')}
            </Button>
          </div>

          <div className="space-y-2">
            <Label>{t('adminCatalog.fields.description')}</Label>
            <Textarea rows={3} value={draft.description ?? ''} onChange={(e) => update({ description: e.target.value })} />
          </div>

          {categoryHint && (
            <p className="text-xs text-muted-foreground">
              {t('adminCatalog.aiEnrich.categoryHint', { hint: categoryHint })}
            </p>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.domainType')}</Label>
              <Select
                value={draft.domain_type ? String(draft.domain_type) : undefined}
                onValueChange={(v) => update({ domain_type: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(domainTypes ?? []).map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.status')}</Label>
              <Select
                value={draft.status ? String(draft.status) : undefined}
                onValueChange={(v) => update({ status: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(statuses ?? []).map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>
                      {productStatusLabelKey(s.code) ? t(productStatusLabelKey(s.code)) : s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.category')}</Label>
              <Select
                value={draft.category ? String(draft.category) : undefined}
                onValueChange={(v) => update({ category: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(categories ?? []).map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.uom')}</Label>
              <Select
                value={draft.uom ? String(draft.uom) : undefined}
                onValueChange={(v) => update({ uom: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(units ?? []).map((u) => (
                    <SelectItem key={u.id} value={String(u.id)}>{u.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.manufacturer')}</Label>
              <Select
                value={draft.brand ? String(draft.brand) : undefined}
                onValueChange={(v) => update({ brand: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(manufacturers ?? []).map((m) => (
                    <SelectItem key={m.id} value={String(m.id)}>{m.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.partNumber')}</Label>
              <Input
                value={draft.manufacturer_part_number ?? ''}
                onChange={(e) => update({ manufacturer_part_number: e.target.value })}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>{t('adminCatalog.fields.gost')}</Label>
            <Input value={draft.gost_drawing ?? ''} onChange={(e) => update({ gost_drawing: e.target.value })} />
          </div>

          {isRailway && (
            <div className="space-y-2">
              <Label>
                {t('adminCatalog.fields.equipmentGroups')}
                <span className="ml-1 text-destructive">*</span>
              </Label>
              <p className="text-xs text-muted-foreground">{t('adminCatalog.equipmentGroupsHint')}</p>
              <div className="max-h-44 space-y-2 overflow-y-auto rounded-md border p-3">
                {(equipmentGroups ?? []).length === 0 && (
                  <p className="text-xs text-muted-foreground">{t('pages.common.noData')}</p>
                )}
                {(equipmentGroups ?? []).map((g) => (
                  <label key={g.id} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={groupIds.includes(g.id)}
                      onCheckedChange={() => toggleGroup(g.id)}
                    />
                    {g.name}
                  </label>
                ))}
              </div>
            </div>
          )}

          {sellerMode && (
            <>
              <Separator />
              <div className="space-y-1">
                <Label className="text-base">{t('adminCatalog.pricing.title')}</Label>
                <p className="text-xs text-muted-foreground">{t('adminCatalog.pricing.hint')}</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label>{t('adminOffers.fields.basePrice')}</Label>
                  <Input
                    type="number"
                    min="0"
                    step="0.01"
                    value={offerDraft.base_price ?? ''}
                    onChange={(e) => updateOffer({ base_price: e.target.value })}
                  />
                </div>
                <div className="space-y-2">
                  <Label>{t('adminOffers.fields.currency')}</Label>
                  <Select
                    value={offerDraft.currency ? String(offerDraft.currency) : undefined}
                    onValueChange={(v) => updateOffer({ currency: Number(v) })}
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
                  <Label>{t('adminOffers.fields.stockStatus')}</Label>
                  <Select
                    value={offerDraft.stock_status ? String(offerDraft.stock_status) : undefined}
                    onValueChange={(v) => updateOffer({ stock_status: Number(v) })}
                  >
                    <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                    <SelectContent>
                      {(stockStatuses ?? []).map((s) => (
                        <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>{t('adminOffers.fields.deliveryBasis')}</Label>
                  <Select
                    value={offerDraft.delivery_basis ? String(offerDraft.delivery_basis) : undefined}
                    onValueChange={(v) => updateOffer({ delivery_basis: Number(v) })}
                  >
                    <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                    <SelectContent>
                      {(deliveryBases ?? []).map((d) => (
                        <SelectItem key={d.id} value={String(d.id)}>{d.code}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="space-y-2">
                <Label>{t('adminOffers.fields.supplierSku')}</Label>
                <Input
                  value={offerDraft.supplier_sku ?? ''}
                  onChange={(e) => updateOffer({ supplier_sku: e.target.value })}
                />
              </div>
            </>
          )}

          {isEdit && target?.sku && (
            <>
              <Separator />
              <div className="text-xs text-muted-foreground">
                {t('adminCatalog.fields.sku')}: <span className="font-mono">{target.sku}</span>
              </div>
            </>
          )}

          {isEdit && target?.id && (
            <>
              <Separator />
              <ProductMediaSection productId={target.id} />
            </>
          )}
          {!isEdit && (
            <p className="text-xs text-muted-foreground">
              {t('adminCatalog.mediaAfterCreate')}
            </p>
          )}
        </div>

        <SheetFooter className="mt-6">
          <Button onClick={submit} disabled={busy} className="w-full">
            {isEdit ? t('adminCatalog.save') : t('adminCatalog.create')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export function AdminCatalogPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['domain', 'status'] as const, { defaultOrdering: 'name' });
  const { data: products, isLoading, isError, refetch } = useProducts({
    search: listParams.search || undefined,
    domain_type: listParams.filters.domain === 'all' ? undefined : listParams.filters.domain,
    // Fetch the complete set so client-side search/sort/Pager + stat tiles are accurate
    // (DRF caps each page at 20; H4). Server already filters by search/domain.
    fetchAll: true,
  });
  const { data: domainTypes } = useDomainTypes();
  const { data: statuses } = useProductStatuses();
  const deleteMut = useDeleteProduct();
  const publishMut = useBulkPublishProducts();

  const [sheetOpen, setSheetOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Product | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Product | null>(null);
  const [publishTarget, setPublishTarget] = useState<Product | null>(null);

  const onEdit = (p: Product) => {
    setEditTarget(p);
    setSheetOpen(true);
  };
  const onNew = () => {
    setEditTarget(null);
    setSheetOpen(true);
  };

  const onDelete = async () => {
    if (!deleteTarget) return;
    await deleteMut.mutateAsync(deleteTarget.id);
    toast.success(t('adminCatalog.deleted'));
  };

  const onPublish = async () => {
    if (!publishTarget) return;
    await publishMut.mutateAsync([publishTarget.id]);
    toast.success(t('adminCatalog.published'));
  };

  // A product with a blank/DRAFT status is never PUBLISHED and has no other way to
  // go live — surface a quick publish affordance on those rows only.
  const canPublish = (p: Product) => p.status_code !== 'PUBLISHED';

  const stats = [
    { label: t('adminCatalog.stats.total'), value: String(products?.length ?? '—') },
    {
      label: t('adminCatalog.stats.published'),
      value: String(products?.filter((p) => p.status_code === 'PUBLISHED').length ?? '—'),
    },
    {
      label: t('adminCatalog.stats.draft'),
      value: String(products?.filter((p) => p.status_code === 'DRAFT').length ?? '—'),
    },
  ];

  return (
    <PageShell
      title={t('adminCatalog.title')}
      description={t('adminCatalog.description')}
      icon={<Package className="h-5 w-5" />}
      stats={stats}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('adminCatalog.searchPlaceholder')}
        filters={[
          {
            key: 'domain',
            value: listParams.filters.domain,
            onChange: (v) => listParams.setFilter('domain', v),
            allLabel: t('adminCatalog.allDomains'),
            options: (domainTypes ?? []).map((d) => ({ value: d.code, label: d.name })),
          },
          {
            key: 'status',
            value: listParams.filters.status,
            onChange: (v) => listParams.setFilter('status', v),
            allLabel: t('adminCatalog.allStatuses'),
            options: (statuses ?? []).map((s) => ({
              value: s.code,
              label: productStatusLabelKey(s.code) ? t(productStatusLabelKey(s.code)) : s.name,
            })),
          },
        ]}
        newLabel={t('adminCatalog.newProduct')}
        onNew={onNew}
      />

      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(products ?? [], listParams, {
              searchFields: () => [],
              filterPredicates: {
                status: (p, v) => p.status_code === v,
              },
              sortAccessors: {
                sku: (p) => p.sku ?? '',
                name: (p) => p.name ?? '',
                domain: (p) => p.domain_type_name ?? '',
                status: (p) => p.status_name ?? '',
                manufacturer: (p) => p.brand_name ?? '',
              },
            });
            if (isLoading) return <LoadingRows rows={6} />;
            if (isError) return <ErrorState onRetry={() => refetch()} />;
            if (!pageItems.length) return <EmptyState icon={<Package className="h-5 w-5" />} message={t('adminCatalog.emptyState')} />;
            return (
            <>
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead sortKey="sku" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCatalog.table.sku')}</SortableHead>
                  <SortableHead sortKey="name" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCatalog.table.name')}</SortableHead>
                  <SortableHead sortKey="domain" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCatalog.table.domain')}</SortableHead>
                  <SortableHead sortKey="status" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCatalog.table.status')}</SortableHead>
                  <SortableHead sortKey="manufacturer" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCatalog.table.manufacturer')}</SortableHead>
                  <TableHead className="text-right">{t('adminCatalog.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-mono text-xs">{p.sku ?? '—'}</TableCell>
                    <TableCell>{p.name}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">{p.domain_type_name || '—'}</TableCell>
                    <TableCell><Badge variant="outline">{productStatusLabelKey(p.status_code) ? t(productStatusLabelKey(p.status_code)) : (p.status_name || '—')}</Badge></TableCell>
                    <TableCell className="text-muted-foreground text-xs">{p.brand_name ?? '—'}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        {canPublish(p) && (
                          <Button variant="ghost" size="sm" onClick={() => setPublishTarget(p)} title={t('adminCatalog.publish')}>
                            <Send className="h-3.5 w-3.5 text-primary" />
                          </Button>
                        )}
                        <Button variant="ghost" size="sm" onClick={() => onEdit(p)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(p)}>
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

      <ProductFormSheet open={sheetOpen} onOpenChange={setSheetOpen} target={editTarget} />

      <ConfirmActionDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={t('adminCatalog.confirmDelete')}
        description={t('adminCatalog.confirmDeleteDesc', { name: deleteTarget?.name })}
        variant="destructive"
        confirmLabel={t('adminCatalog.delete')}
        cancelLabel={t('adminCatalog.cancel')}
        onConfirm={onDelete}
      />

      <ConfirmActionDialog
        open={!!publishTarget}
        onOpenChange={(o) => !o && setPublishTarget(null)}
        title={t('adminCatalog.confirmPublish')}
        description={t('adminCatalog.confirmPublishDesc', { name: publishTarget?.name })}
        variant="primary"
        confirmLabel={t('adminCatalog.publish')}
        cancelLabel={t('adminCatalog.cancel')}
        onConfirm={onPublish}
      />
    </PageShell>
  );
}

export default AdminCatalogPage;
