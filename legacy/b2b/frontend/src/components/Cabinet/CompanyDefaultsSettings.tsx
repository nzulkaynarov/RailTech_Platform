import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Loader2, Shield, Sliders } from 'lucide-react';

import { accountsApi, CompanySettings, CompanySettingsUpdate } from '@/api/accountsApi';
import { currencyLabelKey, deliveryBasisLabelKey } from '@/lib/codes';
import { useAuthStore } from '@/store/authStore';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { useDraftState } from '@/hooks/useDraftState';
import { useCurrencies, useDeliveryBases } from '@/hooks/useMasterData';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

// Sentinel for the "no default" option — shadcn Select can't hold an empty value.
const NONE = '__none__';

type DefaultsForm = {
  default_cost_currency: string;
  default_delivery_basis: string;
  default_vat_rate: string;
  default_margin_percent: string;
  min_margin_percent: string;
  target_margin_percent: string;
  default_offer_validity_days: string;
  payment_terms_days: string;
  default_payment_terms: string;
  default_warranty_months: string;
};

const EMPTY_FORM: DefaultsForm = {
  default_cost_currency: NONE,
  default_delivery_basis: NONE,
  default_vat_rate: '',
  default_margin_percent: '',
  min_margin_percent: '',
  target_margin_percent: '',
  default_offer_validity_days: '',
  payment_terms_days: '',
  default_payment_terms: '',
  default_warranty_months: '',
};

function toForm(settings: CompanySettings): DefaultsForm {
  return {
    default_cost_currency: settings.default_cost_currency_code || NONE,
    default_delivery_basis: settings.default_delivery_basis_code || NONE,
    default_vat_rate: settings.default_vat_rate ?? '',
    default_margin_percent: settings.default_margin_percent ?? '',
    min_margin_percent: settings.min_margin_percent ?? '',
    target_margin_percent: settings.target_margin_percent ?? '',
    default_offer_validity_days:
      settings.default_offer_validity_days != null
        ? String(settings.default_offer_validity_days)
        : '',
    payment_terms_days: settings.payment_terms_days != null ? String(settings.payment_terms_days) : '',
    default_payment_terms: settings.default_payment_terms ?? '',
    default_warranty_months:
      settings.default_warranty_months != null ? String(settings.default_warranty_months) : '',
  };
}

/**
 * Company-Admin (OWNER) org-admin zone: the КП defaults a selling company sets once.
 * A new КП pre-fills the Incoterm, валюта себестоимости, ставку НДС, маржу and validity
 * from here so the sales team isn't re-entering them on every offer. Wired to the
 * OWNER-gated /companies/{id}/settings/ endpoint (FK defaults sent as master-data CODES).
 */
export function CompanyDefaultsSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const { data: currencies = [] } = useCurrencies();
  const { data: bases = [] } = useDeliveryBases();

  const companyId = user?.company?.id ?? user?.primary_company?.id ?? null;
  const canEditSettings = useHasCompanyPermission('settings.edit');

  const { data: settings, isLoading } = useQuery({
    queryKey: ['company-settings', companyId],
    queryFn: () => accountsApi.getCompanySettings(companyId as number),
    enabled: companyId != null && canEditSettings,
  });

  // Форма пересобирается при СМЕНЕ загруженных настроек, прямо в рендере: эффект показал бы
  // пустую форму на кадр, а потом заполненную (react.dev, «You Might Not Need an Effect»).
  const [form, setForm] = useDraftState(settings ?? null, (loaded) => (loaded ? toForm(loaded) : EMPTY_FORM));

  const saveMut = useMutation({
    mutationFn: (data: CompanySettingsUpdate) =>
      accountsApi.updateCompanySettings(companyId as number, data),
    onSuccess: (updated) => {
      queryClient.setQueryData(['company-settings', companyId], updated);
      toast.success(t('companyDefaults.saved'));
    },
    onError: () => toast.error(t('common.error')),
  });

  if (!canEditSettings) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-border bg-muted/40 p-4">
        <Shield className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm font-medium text-muted-foreground">{t('companyDefaults.ownerOnly')}</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex p-10 justify-center" role="status">
        <Loader2 className="h-8 w-8 text-muted-foreground animate-spin" aria-hidden="true" />
        <span className="sr-only">{t('common.loading')}</span>
      </div>
    );
  }

  const handleSave = () => {
    const vat = form.default_vat_rate.trim() !== '' ? Number(form.default_vat_rate) : null;
    const defMargin = form.default_margin_percent.trim() !== '' ? Number(form.default_margin_percent) : null;
    const minMargin = form.min_margin_percent.trim() !== '' ? Number(form.min_margin_percent) : null;
    const targetMargin = form.target_margin_percent.trim() !== '' ? Number(form.target_margin_percent) : null;
    const validityDays = form.default_offer_validity_days.trim() !== '' ? Number(form.default_offer_validity_days) : null;
    const paymentDays = form.payment_terms_days.trim() !== '' ? Number(form.payment_terms_days) : null;
    const warrantyMonths = form.default_warranty_months.trim() !== '' ? Number(form.default_warranty_months) : null;

    if (vat !== null && (vat < 0 || vat > 100 || isNaN(vat))) {
      toast.error(t('companyDefaults.errors.invalidVat'));
      return;
    }
    if (defMargin !== null && (defMargin < 0 || isNaN(defMargin))) {
      toast.error(t('companyDefaults.errors.invalidMargin'));
      return;
    }
    if (minMargin !== null && (minMargin < 0 || isNaN(minMargin))) {
      toast.error(t('companyDefaults.errors.invalidMargin'));
      return;
    }
    if (targetMargin !== null && (targetMargin < 0 || isNaN(targetMargin))) {
      toast.error(t('companyDefaults.errors.invalidMargin'));
      return;
    }
    if (validityDays !== null && (validityDays < 0 || isNaN(validityDays))) {
      toast.error(t('companyDefaults.errors.invalidValidity'));
      return;
    }
    if (warrantyMonths !== null && (warrantyMonths < 0 || isNaN(warrantyMonths))) {
      toast.error(t('companyDefaults.errors.invalidWarranty'));
      return;
    }

    if (minMargin !== null && defMargin !== null && minMargin > defMargin) {
      toast.error(t('companyDefaults.errors.minMarginGreaterThanDefault'));
      return;
    }
    if (defMargin !== null && targetMargin !== null && defMargin > targetMargin) {
      toast.error(t('companyDefaults.errors.defaultMarginGreaterThanTarget'));
      return;
    }
    if (minMargin !== null && targetMargin !== null && minMargin > targetMargin) {
      toast.error(t('companyDefaults.errors.minMarginGreaterThanTarget'));
      return;
    }

    saveMut.mutate({
      default_cost_currency: form.default_cost_currency === NONE ? '' : form.default_cost_currency,
      default_delivery_basis: form.default_delivery_basis === NONE ? '' : form.default_delivery_basis,
      default_vat_rate: form.default_vat_rate.trim() === '' ? null : form.default_vat_rate.trim(),
      default_margin_percent:
        form.default_margin_percent.trim() === '' ? null : form.default_margin_percent.trim(),
      min_margin_percent:
        form.min_margin_percent.trim() === '' ? null : form.min_margin_percent.trim(),
      target_margin_percent:
        form.target_margin_percent.trim() === '' ? null : form.target_margin_percent.trim(),
      default_offer_validity_days: validityDays,
      payment_terms_days: paymentDays,
      default_payment_terms: form.default_payment_terms.trim(),
      default_warranty_months: warrantyMonths,
    });
  };

  // §2.4 reading-form pattern: section header left, form card right with a width cap.
  return (
    <div className="grid items-start gap-6 lg:grid-cols-[240px_1fr]">
      <div>
        <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
          <Sliders className="h-5 w-5 text-primary" aria-hidden="true" />
          {t('companyDefaults.title')}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('companyDefaults.subtitle')}</p>
      </div>

      <Card className="min-w-0 max-w-2xl">
        <CardContent className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="cd-delivery-basis">{t('companyDefaults.deliveryBasis')}</Label>
              <Select
                value={form.default_delivery_basis}
                onValueChange={(val) => setForm({ ...form, default_delivery_basis: val })}
              >
                <SelectTrigger id="cd-delivery-basis">
                  <SelectValue placeholder={t('companyDefaults.notSet')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>{t('companyDefaults.notSet')}</SelectItem>
                  {bases.map((basis) => (
                    <SelectItem key={basis.code} value={basis.code}>
                      {basis.code} — {deliveryBasisLabelKey(basis.code) ? t(deliveryBasisLabelKey(basis.code)) : basis.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="cd-currency">{t('companyDefaults.costCurrency')}</Label>
              <Select
                value={form.default_cost_currency}
                onValueChange={(val) => setForm({ ...form, default_cost_currency: val })}
              >
                <SelectTrigger id="cd-currency">
                  <SelectValue placeholder={t('companyDefaults.notSet')} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>{t('companyDefaults.notSet')}</SelectItem>
                  {currencies.map((currency) => {
                    const currencyName = currencyLabelKey(currency.code)
                      ? t(currencyLabelKey(currency.code))
                      : currency.name;
                    return (
                      <SelectItem key={currency.code} value={currency.code}>
                        {currency.code}{currencyName ? ` — ${currencyName}` : ''}
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="cd-vat">{t('companyDefaults.vatRate')}</Label>
              <Input
                id="cd-vat"
                type="number"
                step="0.01"
                min="0"
                value={form.default_vat_rate}
                onChange={(e) => setForm({ ...form, default_vat_rate: e.target.value })}
                placeholder="12"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="cd-margin">{t('companyDefaults.marginPercent')}</Label>
              <Input
                id="cd-margin"
                type="number"
                step="0.01"
                min="0"
                value={form.default_margin_percent}
                onChange={(e) => setForm({ ...form, default_margin_percent: e.target.value })}
                placeholder="15"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="cd-min-margin">{t('companyDefaults.minMarginPercent')}</Label>
              <Input
                id="cd-min-margin"
                type="number"
                step="0.01"
                min="0"
                value={form.min_margin_percent}
                onChange={(e) => setForm({ ...form, min_margin_percent: e.target.value })}
                placeholder="15"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="cd-target-margin">{t('companyDefaults.targetMarginPercent')}</Label>
              <Input
                id="cd-target-margin"
                type="number"
                step="0.01"
                min="0"
                value={form.target_margin_percent}
                onChange={(e) => setForm({ ...form, target_margin_percent: e.target.value })}
                placeholder="25"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="cd-validity">{t('companyDefaults.offerValidityDays')}</Label>
              <Input
                id="cd-validity"
                type="number"
                step="1"
                min="0"
                value={form.default_offer_validity_days}
                onChange={(e) => setForm({ ...form, default_offer_validity_days: e.target.value })}
                placeholder="30"
              />
            </div>

            {/* G3: МАШИННЫЙ срок оплаты — от него считается дата в счёте и напоминание.
                Не путать с текстовым «Условия оплаты» ниже: из текста дату не посчитать. */}
            <div className="space-y-2">
              <Label htmlFor="cd-payment-days">{t('companyDefaults.paymentTermsDays')}</Label>
              <Input
                id="cd-payment-days"
                type="number"
                step="1"
                min="0"
                value={form.payment_terms_days}
                onChange={(e) => setForm({ ...form, payment_terms_days: e.target.value })}
                placeholder="14"
              />
              <p className="text-xs text-muted-foreground">{t('companyDefaults.paymentTermsDaysHint')}</p>
            </div>

            {/* spec-kp-blank: dynamic «Условия поставки» defaults printed on the КП. */}
            <div className="space-y-2">
              <Label htmlFor="cd-payment">{t('companyDefaults.paymentTerms')}</Label>
              <Input
                id="cd-payment"
                value={form.default_payment_terms}
                onChange={(e) => setForm({ ...form, default_payment_terms: e.target.value })}
                placeholder={t('companyDefaults.paymentTermsPlaceholder')}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cd-warranty">{t('companyDefaults.warrantyMonths')}</Label>
              <Input
                id="cd-warranty"
                type="number"
                step="1"
                min="0"
                value={form.default_warranty_months}
                onChange={(e) => setForm({ ...form, default_warranty_months: e.target.value })}
                placeholder="12"
              />
            </div>
          </div>

          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">{t('companyDefaults.marginHelp')}</p>
            <p className="text-xs text-muted-foreground">{t('companyDefaults.help')}</p>
          </div>
        </CardContent>

        <CardFooter>
          <Button onClick={handleSave} disabled={saveMut.isPending}>
            {saveMut.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            {t('common.save')}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

export default CompanyDefaultsSettings;
