import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Loader2, Shield, Sliders } from 'lucide-react';

import { accountsApi, CompanySettings, CompanySettingsUpdate } from '@/api/accountsApi';
import { useAuthStore } from '@/store/authStore';
import { useCurrencies, useDeliveryBases } from '@/hooks/useMasterData';
import { Button } from '@/components/ui/button';
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
  default_offer_validity_days: string;
};

const EMPTY_FORM: DefaultsForm = {
  default_cost_currency: NONE,
  default_delivery_basis: NONE,
  default_vat_rate: '',
  default_margin_percent: '',
  default_offer_validity_days: '',
};

function toForm(settings: CompanySettings): DefaultsForm {
  return {
    default_cost_currency: settings.default_cost_currency_code || NONE,
    default_delivery_basis: settings.default_delivery_basis_code || NONE,
    default_vat_rate: settings.default_vat_rate ?? '',
    default_margin_percent: settings.default_margin_percent ?? '',
    default_offer_validity_days:
      settings.default_offer_validity_days != null
        ? String(settings.default_offer_validity_days)
        : '',
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
  const isOwner = user?.workspace_role === 'OWNER';

  const [form, setForm] = useState<DefaultsForm>(EMPTY_FORM);

  const { data: settings, isLoading } = useQuery({
    queryKey: ['company-settings', companyId],
    queryFn: () => accountsApi.getCompanySettings(companyId as number),
    enabled: companyId != null && isOwner,
  });

  useEffect(() => {
    if (settings) setForm(toForm(settings));
  }, [settings]);

  const saveMut = useMutation({
    mutationFn: (data: CompanySettingsUpdate) =>
      accountsApi.updateCompanySettings(companyId as number, data),
    onSuccess: (updated) => {
      queryClient.setQueryData(['company-settings', companyId], updated);
      toast.success(t('companyDefaults.saved'));
    },
    onError: () => toast.error(t('common.error')),
  });

  if (!isOwner) {
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
    saveMut.mutate({
      default_cost_currency: form.default_cost_currency === NONE ? '' : form.default_cost_currency,
      default_delivery_basis: form.default_delivery_basis === NONE ? '' : form.default_delivery_basis,
      default_vat_rate: form.default_vat_rate.trim() === '' ? null : form.default_vat_rate.trim(),
      default_margin_percent:
        form.default_margin_percent.trim() === '' ? null : form.default_margin_percent.trim(),
      default_offer_validity_days:
        form.default_offer_validity_days.trim() === ''
          ? null
          : Number(form.default_offer_validity_days),
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
          <Sliders className="h-5 w-5 text-primary" aria-hidden="true" />
          {t('companyDefaults.title')}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('companyDefaults.subtitle')}</p>
      </div>

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
                  {basis.code} — {basis.name}
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
              {currencies.map((currency) => (
                <SelectItem key={currency.code} value={currency.code}>
                  {currency.code}{currency.name ? ` — ${currency.name}` : ''}
                </SelectItem>
              ))}
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
      </div>

      <p className="text-xs text-muted-foreground">{t('companyDefaults.help')}</p>

      <Button onClick={handleSave} disabled={saveMut.isPending}>
        {saveMut.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
        {t('common.save')}
      </Button>
    </div>
  );
}

export default CompanyDefaultsSettings;
