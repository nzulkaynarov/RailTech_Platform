import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Eye } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { useSetProductVisibility } from '@/hooks/useCatalog';
import { extractApiErrorCode, translateApiError } from '@/lib/apiError';
import type { CatalogVisibility, FulfillmentPolicy, Product } from '@/api/catalogApi';
import type { ProductFormState } from '@/components/Shared/product-form/useProductForm';

import { ClientPreview } from './ClientPreview';
import { SECTION_IDS } from './anchors';

const POLICIES: FulfillmentPolicy[] = ['fixed', 'milestones', 'time'];
const VISIBILITIES: CatalogVisibility[] = ['on_request', 'cabinet'];

/**
 * «Для клиента» — опубликованный слой карточки (M1-ERP-07). Эталон — вкладки Odoo «Продажи /
 * Сайт»: что клиент увидит, по какой цене и как услугу окажут. Всё, что здесь, уходит клиенту
 * только через проекцию сервера; внутреннее — в соседней секции «Только для сотрудников».
 *
 * Видимость («цена в кабинете» / «по запросу») — решение публикации: меняется сразу действием
 * под правом `catalog.publish`, без права — только читается.
 */
export function ClientLayerSection({ form, product }: { form: ProductFormState; product?: Product }) {
  const { t } = useTranslation();
  const { draft, update, currencies, kind } = form;
  const canPublish = useHasCompanyPermission('catalog.publish');
  const visibilityMut = useSetProductVisibility();
  const visibility: CatalogVisibility = product?.visibility ?? 'on_request';

  const changeVisibility = async (next: string) => {
    if (!product || next === visibility) return;
    try {
      await visibilityMut.mutateAsync({ id: product.id, visibility: next as CatalogVisibility });
      toast.success(t('productEditor.visibility.changed'));
    } catch (err) {
      toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('productEditor.actions.failed'));
    }
  };

  return (
    <section id={SECTION_IDS.client} className="scroll-mt-20">
      <Card>
        <CardHeader className="space-y-1 pb-3">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="text-base">{t('productEditor.layers.clientTitle')}</CardTitle>
            <StatusBadge
              label={t('productEditor.layers.clientBadge')}
              variant="info"
              icon={<Eye className="size-3.5" aria-hidden="true" />}
            />
          </div>
          <p className="text-xs text-muted-foreground">{t('productEditor.layers.clientHint')}</p>
        </CardHeader>
        <CardContent className="space-y-5">
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">{t('productEditor.visibility.label')}</legend>
            {canPublish && product ? (
              <RadioGroup
                value={visibility}
                onValueChange={changeVisibility}
                disabled={visibilityMut.isPending}
                className="grid gap-2 sm:grid-cols-2"
              >
                {VISIBILITIES.map((option) => (
                  <Label
                    key={option}
                    htmlFor={`pe-visibility-${option}`}
                    className="flex cursor-pointer items-start gap-2 rounded-md border p-3 font-normal has-[[data-state=checked]]:border-primary"
                  >
                    <RadioGroupItem id={`pe-visibility-${option}`} value={option} className="mt-0.5" />
                    <span className="space-y-0.5">
                      <span className="block text-sm font-medium">{t(`productEditor.visibility.${option}`)}</span>
                      <span className="block text-xs text-muted-foreground">
                        {t(`productEditor.visibility.${option}Hint`)}
                      </span>
                    </span>
                  </Label>
                ))}
              </RadioGroup>
            ) : (
              <p className="text-sm">
                {t(`productEditor.visibility.${visibility}`)}
                <span className="block text-xs text-muted-foreground">
                  {product ? t('productEditor.visibility.readOnly') : t('productEditor.visibility.afterDraft')}
                </span>
              </p>
            )}
          </fieldset>

          {kind === 'service' && (
            <div className="space-y-2">
              <Label htmlFor="pe-policy">{t('productEditor.policy.label')}</Label>
              <Select
                value={draft.fulfillment_policy || undefined}
                onValueChange={(value) => update({ fulfillment_policy: value as FulfillmentPolicy })}
              >
                <SelectTrigger id="pe-policy"><SelectValue placeholder={t('productEditor.policy.placeholder')} /></SelectTrigger>
                <SelectContent>
                  {POLICIES.map((policy) => (
                    <SelectItem key={policy} value={policy}>{t(`productEditor.policy.${policy}`)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {t(draft.fulfillment_policy === 'time' ? 'productEditor.policy.timeHint' : 'productEditor.policy.hint')}
              </p>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="pe-list-price">{t('productEditor.price.label')}</Label>
              <Input
                id="pe-list-price"
                type="number"
                min="0"
                step="0.01"
                inputMode="decimal"
                value={draft.list_price ?? ''}
                onChange={(e) => update({ list_price: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="pe-list-currency">{t('productEditor.price.currency')}</Label>
              <Select
                value={draft.list_price_currency ? String(draft.list_price_currency) : undefined}
                onValueChange={(value) => update({ list_price_currency: Number(value) })}
              >
                <SelectTrigger id="pe-list-currency"><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(currencies ?? []).map((currency) => (
                    <SelectItem key={currency.id} value={String(currency.id)}>{currency.code}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="pe-lead-time">{t('productEditor.price.leadTime')}</Label>
              <Input
                id="pe-lead-time"
                type="number"
                min="0"
                step="1"
                inputMode="numeric"
                value={draft.client_lead_time_days ?? ''}
                onChange={(e) => update({
                  client_lead_time_days: e.target.value === '' ? null : Number(e.target.value),
                })}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">{t('productEditor.price.hint')}</p>

          {product?.client_preview && (
            <ClientPreview preview={product.client_preview} published={product.status_code === 'PUBLISHED'} />
          )}
        </CardContent>
      </Card>
    </section>
  );
}
