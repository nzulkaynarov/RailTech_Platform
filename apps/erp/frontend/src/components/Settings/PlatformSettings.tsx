/**
 * Platform SystemSettings CRUD (Platform Operator only) — вынесен из SettingsPage.tsx
 * как есть (spec PR 1, файл-лимит 500 строк); поведение и вёрстка без изменений.
 */
import { useDraftState } from '@/hooks/useDraftState';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ShieldCheck, ExternalLink } from 'lucide-react';

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
  // без промежуточного кадра с пустыми полями. Редактируется только НДС: имя, почта поддержки, логотип и
  // домен общие для ансамбля и ведутся в CRM (FIX-42) — они выводятся для просмотра и в запрос не попадают.
  const [form, setForm] = useDraftState(data ?? null, (loaded) => ({ vatRate: loaded?.vat_rate ?? '' }));
  const { vatRate } = form;
  const setVatRate = (value: string) => setForm((prev) => ({ ...prev, vatRate: value }));
  const platformName = data?.platform_name ?? '';
  const supportEmail = data?.support_email ?? '';
  const logoUrl = data?.logo_url ?? '';
  const domain = data?.domain ?? '';
  // Ссылка ведёт на настройки CRM по адресу, который отдаёт бэкенд; без адреса кнопки нет (не ведём в админку ERP).
  const crmSettingsUrl = data?.crm_frontend_url ? `${data.crm_frontend_url.replace(/\/+$/, '')}/settings` : null;

  const handleSave = async () => {
    try {
      // standard_margin removed (P9): it was inert — the pricing engine reads
      // CompanySettings.default_margin_percent, not this platform setting.
      await updateMut.mutateAsync({ vat_rate: vatRate });
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
            <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-0.5">
                <p className="text-sm font-medium">{t('settings.platform.managedInCrm')}</p>
                <p className="text-xs text-muted-foreground">{t('settings.platform.managedInCrmHint')}</p>
              </div>
              {crmSettingsUrl && (
                <Button variant="outline" size="sm" asChild>
                  <a href={crmSettingsUrl} target="_blank" rel="noopener noreferrer">
                    <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                    {t('settings.platform.goToCrm')}
                  </a>
                </Button>
              )}
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>{t('settings.platform.vatRate')}</Label>
                <Input type="number" step="0.01" value={vatRate} onChange={(e) => setVatRate(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.platformName')}</Label>
                <Input value={platformName} readOnly disabled />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.supportEmail')}</Label>
                <Input type="email" value={supportEmail} readOnly disabled />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.logoUrl')}</Label>
                <Input value={logoUrl} readOnly disabled />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.domain')}</Label>
                <Input value={domain} readOnly disabled />
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
