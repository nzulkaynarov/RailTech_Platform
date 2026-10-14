import { useTranslation } from 'react-i18next';
import { Lock } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { Textarea } from '@/components/ui/textarea';
import { useUserStore } from '@/store/userStore';
import { formatMoney } from '@/utils/decimal';
import type { Product } from '@/api/catalogApi';
import { OfferSection } from '@/components/Shared/product-form/OfferSection';
import type { ProductFormState } from '@/components/Shared/product-form/useProductForm';

import { SECTION_IDS } from './anchors';

/** Права, с которыми сотрудник видит цены поставщиков (как `COST_VIEW_PERMISSIONS` сервера). */
const COST_PERMISSIONS = ['quote.view_cost_margin', 'catalog.manage', 'supply.manage'];

/**
 * «Только для сотрудников» — внутренний слой карточки (M1-ERP-07; Odoo — вкладка «Закупки»):
 * заметки и предложение поставщика (закупочная цена, наличие и сроки у поставщика). Клиенту это
 * не уходит ни при какой видимости — сервер отдаёт ему только опубликованный слой. Цены
 * поставщика видят роли с правом себестоимости или ведения каталога; править предложение —
 * `supply.manage`.
 */
export function InternalLayerSection({ form, product }: { form: ProductFormState; product?: Product }) {
  const { t } = useTranslation();
  const { draft, update } = form;
  const permissions = useUserStore((s) => s.capabilities.permissions);
  const seesCost = COST_PERMISSIONS.some((code) => permissions.includes(code));
  const canEditOffer = permissions.includes('supply.manage');
  // Сервер отдаёт `offers` только ролям с правом себестоимости (cost-gate) — у остальных список пуст.
  const offers = product?.offers ?? [];

  return (
    <section id={SECTION_IDS.internal} className="scroll-mt-20">
      <Card>
        <CardHeader className="space-y-1 pb-3">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-base">{t('productEditor.layers.internalTitle')}</CardTitle>
            <StatusBadge
              label={t('productEditor.layers.internalBadge')}
              variant="warning"
              icon={<Lock className="size-3.5" aria-hidden="true" />}
            />
          </div>
          <p className="text-xs text-muted-foreground">{t('productEditor.layers.internalHint')}</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="pe-internal-notes">{t('productEditor.layers.internalNotes')}</Label>
            <Textarea
              id="pe-internal-notes"
              rows={3}
              placeholder={t('productEditor.layers.internalNotesPlaceholder')}
              value={draft.internal_notes ?? ''}
              onChange={(e) => update({ internal_notes: e.target.value })}
            />
          </div>
          {offers.length > 0 && (
            <div className="space-y-2">
              <Label>{t('productEditor.layers.offersTitle')}</Label>
              <ul className="divide-y rounded-md border">
                {offers.map((offer) => (
                  <li key={offer.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-2 text-sm">
                    <span className="min-w-0 break-words">
                      {offer.supplier_data?.name ?? '—'}
                      {offer.supplier_sku && (
                        <span className="ml-2 font-mono text-xs text-muted-foreground">{offer.supplier_sku}</span>
                      )}
                    </span>
                    <span className="tabular-nums">
                      {formatMoney(offer.base_price, offer.currency_data?.code ?? undefined)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {form.sellerMode && seesCost && canEditOffer && (
            <>
              <Separator />
              <OfferSection form={form} />
            </>
          )}
          {form.sellerMode && !(seesCost && canEditOffer) && (
            <p className="text-xs text-muted-foreground">{t('productEditor.layers.costHidden')}</p>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
