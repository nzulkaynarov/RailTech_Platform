import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles, Loader2, Landmark } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet';
import { productStatusLabelKey } from '@/lib/codes';
import { CustomsDutiesSheet } from '@/components/Shared/CustomsDutiesSheet';
import type { Product } from '@/api/catalogApi';
import { ProductMediaSection } from './ProductMediaSection';
import { useProductForm } from './useProductForm';
import { AiEnrichPanel } from './AiEnrichPanel';
import { OfferSection } from './OfferSection';
import { HSCodeField } from '@/components/Shared/HSCodeField';
import { ManufacturerField } from '@/components/Shared/ManufacturerField';

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
  const [dutiesOpen, setDutiesOpen] = useState(false);
  // Шторка закрывается после сохранения; страница-редактор (R3) с тем же хуком остаётся на месте.
  const form = useProductForm({ target, sellerCompanyId, open, onSaved: () => onOpenChange(false) });
  const {
    domainTypes, categories, units, adminCompanies,
    draft, categoryHint,
    sellerMode, isEdit, busy, enrichPending,
    aiDailyCap, aiDailyRemaining,
    update, runEnrich, submit,
  } = form;
  // Безлимит (`null`) — это НЕ «осталось 0»; когда бэкенд лимит не прислал, не показываем ничего.
  const aiLimitText = aiDailyCap === undefined && aiDailyRemaining === undefined
    ? ''
    : aiDailyCap === null || aiDailyRemaining === null
      ? t('adminCatalog.aiEnrich.limitUnlimited')
      : t('adminCatalog.aiEnrich.limitLeft', { remaining: aiDailyRemaining ?? 0, cap: aiDailyCap ?? 0 });

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

          {/* N3: оператор создаёт карточку ОТ ИМЕНИ компании — «ничья» карточка недоступна
              продавцу навсегда. На редактировании владелец не меняется (иммутабелен на бэке). */}
          {!sellerMode && !isEdit && (
            <div className="space-y-2">
              <Label>
                {t('adminCatalog.fields.ownerCompany')}
                <span className="ml-1 text-destructive">*</span>
              </Label>
              <Select
                value={draft.owner_company ? String(draft.owner_company) : undefined}
                onValueChange={(v) => update({ owner_company: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(adminCompanies ?? []).map((company) => (
                    <SelectItem key={company.id} value={String(company.id)}>{company.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="flex items-start justify-between gap-3 rounded-md border border-dashed bg-muted/40 p-3">
            <div className="space-y-0.5">
              <p className="text-sm font-medium">{t('adminCatalog.aiEnrich.title')}</p>
              <p className="text-xs text-muted-foreground">{t('adminCatalog.aiEnrich.hint')}</p>
            </div>
            {/* Остаток дневного лимита — ИНФОРМАЦИЯ рядом с кнопкой (Shopify Magic показывает
                расход, но не запирает кнопку): гейт живёт на сервере и ответит 429. */}
            <div className="flex shrink-0 flex-col items-end gap-1">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={runEnrich}
                disabled={enrichPending || !draft.name?.trim()}
              >
                {enrichPending
                  ? <Loader2 className="size-4 animate-spin" />
                  : <Sparkles className="size-4" />}
                {t('adminCatalog.aiEnrich.button')}
              </Button>
              {aiLimitText && <p className="text-xs text-muted-foreground">{aiLimitText}</p>}
            </div>
          </div>

          <AiEnrichPanel form={form} />

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
            {/* N2 (B4): селекта статуса здесь больше НЕТ — статус меняют только сервисы
                публикации (порог полноты), выбор «Опубликован» руками обходил его. */}
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.status')}</Label>
              <div className="flex h-9 items-center rounded-md border bg-muted/40 px-3 text-sm text-muted-foreground">
                {target?.status_code && productStatusLabelKey(target.status_code)
                  ? t(productStatusLabelKey(target.status_code))
                  : (target?.status_name ?? t('nomenclature.tabs.DRAFT'))}
              </div>
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
              {/* N1: свободный ввод с созданием на лету — Select по вечно пустому read-only
                  справочнику был тупиком (наполнить его продавец не мог). */}
              <ManufacturerField
                value={draft.brand_name ?? ''}
                onChange={(brand_name) => update({ brand_name })}
              />
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
            {/* Ставки видны там, где код уже выбран: раньше менеджер уходил за ними на сайт ГТК
                и возвращался переносить цифры руками. Полный код — 10 знаков; у более короткой
                ветки тарифа нет. */}
            {(draft.hs_code ?? '').replace(/\D/g, '').length === 10 && (
              <Button
                type="button"
                variant="link"
                size="sm"
                className="h-auto gap-1 p-0 text-xs"
                onClick={() => setDutiesOpen(true)}
              >
                <Landmark className="h-3.5 w-3.5" aria-hidden="true" />
                {t('customsDuties.action')}
              </Button>
            )}
            <CustomsDutiesSheet
              hsCode={(draft.hs_code ?? '').replace(/\D/g, '')}
              hsName={draft.name ?? ''}
              open={dutiesOpen}
              onOpenChange={setDutiesOpen}
            />
          </div>

          {sellerMode && (
            <>
              <Separator />
              <OfferSection form={form} />
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
