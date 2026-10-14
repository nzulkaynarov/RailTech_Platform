/**
 * Platform SystemSettings CRUD (Platform Operator only) — вынесен из SettingsPage.tsx
 * как есть (spec PR 1, файл-лимит 500 строк); поведение и вёрстка без изменений.
 */
import { useDraftState } from '@/hooks/useDraftState';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ShieldCheck } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

import { useSystemSettings, useUpdateSystemSettings } from '@/hooks/useSystemSettings';

export function PlatformSettings() {
  const { t } = useTranslation();
  const { data, isLoading } = useSystemSettings();
  const updateMut = useUpdateSystemSettings();

  // Одна форма вместо трёх состояний: пересобирается при смене загруженных настроек в рендере,
  // без промежуточного кадра с пустыми полями.
  const [form, setForm] = useDraftState(data ?? null, (loaded) => ({
    vatRate: loaded?.vat_rate ?? '',
    exchangeRate: loaded?.exchange_rate_usd_uzs ?? '',
    platformName: loaded?.platform_name ?? '',
    supportEmail: loaded?.support_email ?? '',
    logoUrl: loaded?.logo_url ?? '',
    domain: loaded?.domain ?? '',
  }));
  const { vatRate, exchangeRate, platformName, supportEmail, logoUrl, domain } = form;
  const setVatRate = (value: string) => setForm((prev) => ({ ...prev, vatRate: value }));
  const setExchangeRate = (value: string) => setForm((prev) => ({ ...prev, exchangeRate: value }));
  const setPlatformName = (value: string) => setForm((prev) => ({ ...prev, platformName: value }));
  const setSupportEmail = (value: string) => setForm((prev) => ({ ...prev, supportEmail: value }));
  const setLogoUrl = (value: string) => setForm((prev) => ({ ...prev, logoUrl: value }));
  const setDomain = (value: string) => setForm((prev) => ({ ...prev, domain: value }));

  const handleSave = async () => {
    try {
      // standard_margin removed (P9): it was inert — the pricing engine reads
      // CompanySettings.default_margin_percent, not this platform setting.
      await updateMut.mutateAsync({
        vat_rate: vatRate,
        exchange_rate_usd_uzs: exchangeRate,
        platform_name: platformName,
        support_email: supportEmail,
        logo_url: logoUrl,
        domain,
      });
      toast.success(t('settings.platform.saved'));
    } catch {
      toast.error(t('settings.platform.saveFailed'));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" />
          {t('settings.platform.title')}
        </CardTitle>
        <CardDescription>{t('settings.platform.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>{t('settings.platform.vatRate')}</Label>
                <Input type="number" step="0.01" value={vatRate} onChange={(e) => setVatRate(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.exchangeRate')}</Label>
                <Input type="number" step="0.0001" value={exchangeRate} onChange={(e) => setExchangeRate(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.platformName')}</Label>
                <Input value={platformName} onChange={(e) => setPlatformName(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.supportEmail')}</Label>
                <Input type="email" value={supportEmail} onChange={(e) => setSupportEmail(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.logoUrl')}</Label>
                <Input value={logoUrl} onChange={(e) => setLogoUrl(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.domain')}</Label>
                <Input value={domain} onChange={(e) => setDomain(e.target.value)} />
              </div>
            </div>

            <Button onClick={handleSave} disabled={updateMut.isPending}>
              {t('settings.platform.save')}
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
