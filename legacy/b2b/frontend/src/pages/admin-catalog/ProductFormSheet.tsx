import { useTranslation } from 'react-i18next';
import { Sparkles, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet';
import { productStatusLabelKey } from '@/lib/codes';
import type { Product } from '@/api/catalogApi';
import { ProductMediaSection } from './ProductMediaSection';
import { useProductForm } from './useProductForm';
import { HSCodeField } from '@/components/Shared/HSCodeField';

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
  const {
    domainTypes, statuses, categories, units, manufacturers, equipmentGroups,
    currencies, stockStatuses, deliveryBases,
    draft, groupIds, offerDraft, categoryHint,
    sellerMode, isEdit, isRailway, busy, enrichPending,
    update, updateOffer, toggleGroup, runEnrich, submit,
  } = useProductForm({ open, onOpenChange, target, sellerCompanyId });

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
              disabled={enrichPending || !draft.name?.trim()}
              className="shrink-0"
            >
              {enrichPending
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
          {/* T1: поля ТН ВЭД в форме НЕ БЫЛО ВОВСЕ — очередь номенклатуры требовала «не хватает:
              Код ТН ВЭД», а ввести его было негде (единственным местом была строка КП). */}
          <div className="space-y-2">
            <Label>{t('adminCatalog.fields.hsCode')}</Label>
            <HSCodeField value={draft.hs_code ?? ''} onChange={(hs_code) => update({ hs_code })} />
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
                    value={offerDraft.stock_quantity ?? 0}
                    onChange={(e) => updateOffer({ stock_quantity: Number(e.target.value) })}
                  />
                </div>
                <div className="space-y-2">
                  <Label>{t('adminOffers.fields.inStockLeadTimeDays')}</Label>
                  <Input
                    type="number"
                    min="0"
                    step="1"
                    value={offerDraft.in_stock_lead_time_days ?? 0}
                    onChange={(e) => updateOffer({ in_stock_lead_time_days: Number(e.target.value) })}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label>{t('adminOffers.fields.orderLeadTimeDays')}</Label>
                <Input
                  type="number"
                  min="0"
                  step="1"
                  value={offerDraft.order_lead_time_days ?? 0}
                  onChange={(e) => updateOffer({ order_lead_time_days: Number(e.target.value) })}
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
