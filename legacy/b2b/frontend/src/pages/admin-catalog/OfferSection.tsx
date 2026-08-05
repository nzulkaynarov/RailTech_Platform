import { useTranslation } from 'react-i18next';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

import type { ProductFormState } from './useProductForm';

/**
 * Коммерческий блок карточки — предложение продавца по этому товару.
 *
 * Вынесен из `ProductFormSheet.tsx` отдельным файлом: форма уже подходила к лимиту в 500
 * строк (панель ИИ вынесли по той же причине), а R7 добавляет сюда пять полей.
 *
 * Эталон — строка прайса поставщика `product.supplierinfo` в Odoo (и info-record в SAP):
 * цена, минимальный заказ, срок поставки и ОКНО ДЕЙСТВИЯ живут одной записью, а снять
 * предложение с продажи можно, не удаляя его. До R7 половина этой записи существовала
 * только в модели: импорт прайса писал MOQ и срок, а продавец не мог ни увидеть их, ни
 * поправить; срок действия цены и деактивацию нельзя было задать нигде.
 */
export function OfferSection({ form }: { form: ProductFormState }) {
  const { t } = useTranslation();
  const { currencies, stockStatuses, deliveryBases, offerDraft, updateOffer } = form;

  return (
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
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label>{t('adminOffers.fields.supplierSku')}</Label>
          <Input
            value={offerDraft.supplier_sku ?? ''}
            onChange={(e) => updateOffer({ supplier_sku: e.target.value })}
          />
        </div>
        {/* MOQ писал импорт прайса, а форма его не показывала: покупатель видел в карточке
            минимальный заказ, которого продавец у себя не находил. */}
        <div className="space-y-2">
          <Label htmlFor="offer-min-order-qty">{t('adminOffers.fields.minQty')}</Label>
          <Input
            id="offer-min-order-qty"
            type="number"
            min="1"
            step="1"
            value={offerDraft.min_order_qty ?? ''}
            onChange={(e) => updateOffer({
              min_order_qty: e.target.value === '' ? undefined : Number(e.target.value),
            })}
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
      {/* Свободный текст срока — то, что печатается в публичной карточке товара. Числовые
          сроки выше кормят авто-разбиение строки КП по наличию (ATP), а эта строка нужна
          там, где срок не сводится к числу («14-21 дн.», «по согласованию»). */}
      <div className="space-y-2">
        <Label htmlFor="offer-delivery-lead-time">{t('adminCatalog.pricing.leadTimeText')}</Label>
        <Input
          id="offer-delivery-lead-time"
          value={offerDraft.delivery_lead_time ?? ''}
          onChange={(e) => updateOffer({ delivery_lead_time: e.target.value })}
        />
        <p className="text-xs text-muted-foreground">{t('adminCatalog.pricing.leadTimeTextHint')}</p>
      </div>
      <div className="space-y-1">
        <Label className="text-base">{t('adminCatalog.pricing.validity')}</Label>
        <p className="text-xs text-muted-foreground">{t('adminCatalog.pricing.validityHint')}</p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="offer-valid-from">{t('adminCatalog.pricing.validFrom')}</Label>
          <Input
            id="offer-valid-from"
            type="date"
            value={offerDraft.valid_from ?? ''}
            onChange={(e) => updateOffer({ valid_from: e.target.value || null })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="offer-valid-until">{t('adminCatalog.pricing.validUntil')}</Label>
          <Input
            id="offer-valid-until"
            type="date"
            value={offerDraft.valid_until ?? ''}
            onChange={(e) => updateOffer({ valid_until: e.target.value || null })}
          />
        </div>
      </div>
      {/* Снятие с продажи, а не удаление: на оффер ссылаются исторические КП, а сезонную
          позицию продавец возвращает в продажу тем же тумблером (архивация в Odoo). */}
      <div className="flex items-start justify-between gap-3 rounded-md border p-3">
        <div className="space-y-0.5">
          <Label htmlFor="offer-is-active">{t('adminCatalog.pricing.isActive')}</Label>
          <p className="text-xs text-muted-foreground">{t('adminCatalog.pricing.isActiveHint')}</p>
        </div>
        <Switch
          id="offer-is-active"
          checked={offerDraft.is_active ?? true}
          onCheckedChange={(checked) => updateOffer({ is_active: checked })}
        />
      </div>
    </>
  );
}
