import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Loader2, Store } from 'lucide-react';

import { accountsApi, type CompanySettings } from '@/api/accountsApi';
import type { PriceVisibility } from '@/api/catalogApi';
import { useAuthStore } from '@/store/authStore';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { useDraftState } from '@/hooks/useDraftState';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

type PolicyForm = { visibility: PriceVisibility; threshold: string };

function toForm(settings?: CompanySettings): PolicyForm {
  return {
    visibility: settings?.catalog_price_visibility ?? 'on_request',
    threshold: String(settings?.catalog_publish_threshold ?? 100),
  };
}

/**
 * Политика каталога компании (M1-ERP-07, ARCHITECTURE §7): видимость цен по умолчанию и порог
 * публикации. Решение владельца 2026-10-13 — цены клиенту только в кабинете, по умолчанию «по
 * запросу»; карточка может переопределить политику. Те же настройки компании, что и умолчания
 * КП (`/companies/{id}/settings/`, право `settings.edit`), поэтому кэш запроса общий.
 */
export function CatalogPolicySettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const companyId = user?.company?.id ?? user?.primary_company?.id ?? null;
  const canEditSettings = useHasCompanyPermission('settings.edit');

  const { data: settings, isLoading } = useQuery({
    queryKey: ['company-settings', companyId],
    queryFn: () => accountsApi.getCompanySettings(companyId as number),
    enabled: companyId != null && canEditSettings,
  });
  const [form, setForm] = useDraftState(settings ? `catalog-policy:${companyId}` : null, () => toForm(settings));

  const saveMut = useMutation({
    mutationFn: () => accountsApi.updateCompanySettings(companyId as number, {
      catalog_price_visibility: form.visibility,
      catalog_publish_threshold: Number(form.threshold),
    }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['company-settings', companyId], updated);
      // Видимость и полнота карточек считаются по политике — карточки перечитываем.
      queryClient.invalidateQueries({ queryKey: ['product'] });
      queryClient.invalidateQueries({ queryKey: ['products'] });
      toast.success(t('catalogPolicy.saved'));
    },
    onError: (err) => toast.error(translateApiError(err)),
  });

  if (!canEditSettings || isLoading) return null;

  const threshold = Number(form.threshold);
  const thresholdValid = Number.isInteger(threshold) && threshold >= 1 && threshold <= 100;

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[240px_1fr]">
      <div>
        <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
          <Store className="h-5 w-5 text-primary" aria-hidden="true" />
          {t('catalogPolicy.title')}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('catalogPolicy.subtitle')}</p>
      </div>

      <Card className="min-w-0 max-w-2xl">
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="cp-visibility">{t('catalogPolicy.priceVisibility')}</Label>
            <Select
              value={form.visibility}
              onValueChange={(value) => setForm({ ...form, visibility: value as PriceVisibility })}
            >
              <SelectTrigger id="cp-visibility" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="on_request">{t('productEditor.publication.visibility.on_request')}</SelectItem>
                <SelectItem value="cabinet">{t('productEditor.publication.visibility.cabinet')}</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">{t('catalogPolicy.priceVisibilityHint')}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="cp-threshold">{t('catalogPolicy.publishThreshold')}</Label>
            <Input
              id="cp-threshold"
              type="number"
              min="1"
              max="100"
              step="1"
              value={form.threshold}
              aria-invalid={!thresholdValid}
              onChange={(e) => setForm({ ...form, threshold: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">{t('catalogPolicy.publishThresholdHint')}</p>
          </div>
        </CardContent>
        <CardFooter>
          <Button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !thresholdValid}>
            {saveMut.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            {t('common.save')}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
