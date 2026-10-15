import { useTranslation } from 'react-i18next';
import { EyeOff } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { StatusBadge, type BadgeVariant } from '@/components/ui/StatusBadge';
import type { FulfillmentPolicy, PriceVisibility, Product, PublishedCatalogItem } from '@/api/catalogApi';

import type { ProductFormState } from '@/components/Shared/product-form/useProductForm';
import { SECTION_IDS } from './anchors';

// shadcn Select не держит пустое значение — «как в политике каталога» живёт под сентинелом.
const POLICY_DEFAULT = '__default__';

const AVAILABILITY_VARIANT: Record<NonNullable<PublishedCatalogItem['availability']>, BadgeVariant> = {
  in_stock: 'success',
  on_order: 'neutral',
  expected: 'info',
};

/**
 * Секция «Для клиента» — опубликованный слой карточки (M1-ERP-07, BUSINESS §10.1).
 *
 * Паттерн «один каталог, два слоя»: всё остальное на странице — внутренний слой бэк-офиса
 * (поставщики, закупочные цены, остатки), а здесь — то, что увидят клиент в кабинете и бот:
 * цена-витрина или «по запросу», для услуг — политика исполнения. Превью справа — ровно та
 * проекция, которую отдаёт портал (`client_preview` с сервера), поэтому сотрудник не гадает,
 * что уйдёт наружу.
 */
export function PublicationSection({ form, product }: { form: ProductFormState; product?: Product }) {
  const { t } = useTranslation();
  const { draft, update, currencies, domainTypes } = form;

  const domainCode = (domainTypes ?? []).find((d) => d.id === Number(draft.domain_type))?.code;
  const isService = domainCode === 'SERVICES';
  const companyDefault: PriceVisibility = product?.price_visibility_default ?? 'on_request';
  const effective: PriceVisibility = draft.price_visibility || companyDefault;

  return (
    <section id={SECTION_IDS.publication} className="scroll-mt-20">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('productEditor.sections.publication')}</CardTitle>
          <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <EyeOff className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            {t('productEditor.publication.internalHidden')}
          </p>
        </CardHeader>
        <CardContent className="grid gap-5 lg:grid-cols-[1fr_minmax(0,18rem)]">
          <div className="min-w-0 space-y-4">
            {isService && (
              <div className="space-y-2">
                <Label htmlFor="pe-fulfillment">{t('productEditor.publication.fulfillmentPolicy')}</Label>
                <Select
                  value={draft.fulfillment_policy || 'fixed'}
                  onValueChange={(value) => update({ fulfillment_policy: value as FulfillmentPolicy })}
                >
                  <SelectTrigger id="pe-fulfillment" className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(['fixed', 'milestones', 'time'] as const).map((policy) => (
                      <SelectItem key={policy} value={policy}>
                        {t(`productEditor.publication.fulfillment.${policy}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">{t('productEditor.publication.fulfillmentHint')}</p>
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="pe-visibility">{t('productEditor.publication.priceVisibility')}</Label>
              <Select
                value={draft.price_visibility || POLICY_DEFAULT}
                onValueChange={(value) => update({
                  price_visibility: value === POLICY_DEFAULT ? '' : (value as PriceVisibility),
                })}
              >
                <SelectTrigger id="pe-visibility" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={POLICY_DEFAULT}>
                    {t(`productEditor.publication.visibility.default_${companyDefault}`)}
                  </SelectItem>
                  <SelectItem value="cabinet">{t('productEditor.publication.visibility.cabinet')}</SelectItem>
                  <SelectItem value="on_request">{t('productEditor.publication.visibility.on_request')}</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {effective === 'cabinet'
                  ? t('productEditor.publication.visibilityHintCabinet')
                  : t('productEditor.publication.visibilityHintOnRequest')}
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="pe-list-price">
                  {t('productEditor.publication.listPrice')}
                  {effective === 'cabinet' && <span className="ml-1 text-destructive">*</span>}
                </Label>
                <Input
                  id="pe-list-price"
                  type="number"
                  min="0"
                  step="0.01"
                  inputMode="decimal"
                  value={draft.list_price ?? ''}
                  onChange={(e) => update({ list_price: e.target.value === '' ? null : e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="pe-list-price-currency">{t('productEditor.publication.listPriceCurrency')}</Label>
                <Select
                  value={draft.list_price_currency ? String(draft.list_price_currency) : undefined}
                  onValueChange={(value) => update({ list_price_currency: Number(value) })}
                >
                  <SelectTrigger id="pe-list-price-currency" className="w-full"><SelectValue placeholder="—" /></SelectTrigger>
                  <SelectContent>
                    {(currencies ?? []).map((currency) => (
                      <SelectItem key={currency.id} value={String(currency.id)}>{currency.code}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">{t('productEditor.publication.listPriceHint')}</p>
          </div>

          <ClientPreview preview={product?.client_preview} />
        </CardContent>
      </Card>
    </section>
  );
}

/** Превью опубликованного слоя по СОХРАНЁННОЙ карточке — та же проекция, что у портала. */
function ClientPreview({ preview }: { preview?: PublishedCatalogItem }) {
  const { t, i18n } = useTranslation();

  return (
    <aside
      aria-label={t('productEditor.publication.previewTitle')}
      className="min-w-0 space-y-2 rounded-lg border border-dashed border-border bg-muted/30 p-3"
    >
      <p className="text-xs font-medium text-muted-foreground">{t('productEditor.publication.previewTitle')}</p>
      {!preview ? (
        <p className="text-sm text-muted-foreground">{t('productEditor.publication.previewNeedsSave')}</p>
      ) : (
        <div className="space-y-2">
          <p className="break-words text-sm font-semibold">{preview.name}</p>
          <p className="text-xs text-muted-foreground">
            {[preview.category, preview.unit].filter(Boolean).join(' · ') || '—'}
          </p>
          <p className="text-base font-semibold tabular-nums">
            {preview.price
              ? new Intl.NumberFormat(i18n.language, { style: 'currency', currency: preview.price.currency })
                  .format(Number(preview.price.amount))
              : t('productEditor.publication.priceOnRequest')}
          </p>
          {preview.availability && (
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge
                label={t(`productEditor.publication.availability.${preview.availability}`)}
                variant={AVAILABILITY_VARIANT[preview.availability]}
              />
              {preview.lead_time_days != null && (
                <span className="text-xs text-muted-foreground">
                  {t('productEditor.publication.leadTime', { count: preview.lead_time_days })}
                </span>
              )}
            </div>
          )}
          {preview.attributes.length > 0 && (
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {preview.attributes.slice(0, 4).map((attribute) => (
                <li key={attribute.name} className="break-words">
                  {attribute.name}: <span className="text-foreground">{attribute.value}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted-foreground">{t('productEditor.publication.previewSavedHint')}</p>
        </div>
      )}
    </aside>
  );
}
