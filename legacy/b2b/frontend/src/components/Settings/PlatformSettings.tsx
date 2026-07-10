/**
 * Platform SystemSettings CRUD (Platform Operator only) — вынесен из SettingsPage.tsx
 * как есть (spec PR 1, файл-лимит 500 строк); поведение и вёрстка без изменений.
 */
import { useState, useEffect } from 'react';
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

  const [vatRate, setVatRate] = useState('');
  const [standardMargin, setStandardMargin] = useState('');
  const [exchangeRate, setExchangeRate] = useState('');
  const [platformName, setPlatformName] = useState('');

  useEffect(() => {
    if (data) {
      setVatRate(data.vat_rate ?? '');
      setStandardMargin(data.standard_margin ?? '');
      setExchangeRate(data.exchange_rate_usd_uzs ?? '');
      setPlatformName(data.platform_name ?? '');
    }
  }, [data]);

  const handleSave = async () => {
    try {
      await updateMut.mutateAsync({
        vat_rate: vatRate,
        standard_margin: standardMargin,
        exchange_rate_usd_uzs: exchangeRate,
        platform_name: platformName,
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
                <Label>{t('settings.platform.standardMargin')}</Label>
                <Input type="number" step="0.01" value={standardMargin} onChange={(e) => setStandardMargin(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.exchangeRate')}</Label>
                <Input type="number" step="0.0001" value={exchangeRate} onChange={(e) => setExchangeRate(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('settings.platform.platformName')}</Label>
                <Input value={platformName} onChange={(e) => setPlatformName(e.target.value)} />
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
