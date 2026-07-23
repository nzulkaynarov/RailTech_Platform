import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Hash, Info, Loader2, Shield } from 'lucide-react';

import { accountsApi } from '@/api/accountsApi';
import { crmApi } from '@/api/crmApi';
import type { NumberingResetPeriod, NumberingSchemeUpdate } from '@/api/crmApi';
import { useAuthStore } from '@/store/authStore';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardFooter } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

// Named preset masks (Odoo ir.sequence-style). `custom` = free-form mask input. The
// server assembles numbers from this token mask (crm/services/numbering.py) — the same
// parser powers the live preview below, so what the user sees is what gets minted.
const PRESETS: { id: string; pattern: string; exampleKey: string }[] = [
  { id: 'brand', pattern: '{prefix}{type}-{YYYY}-{seq}', exampleKey: 'companyNumbering.presetBrandExample' },
  { id: 'slash', pattern: '{type}/{YYYY}/{seq}', exampleKey: 'companyNumbering.presetSlashExample' },
  { id: 'compact', pattern: '{type}-{seq}', exampleKey: 'companyNumbering.presetCompactExample' },
];

const RESET_PERIODS: NumberingResetPeriod[] = ['never', 'yearly', 'monthly'];

// Backend {type} codes → localized «what kind» caption for the preview rows.
const TYPE_LABEL_KEYS: Record<string, string> = {
  KP: 'companyNumbering.types.quote',
  CT: 'companyNumbering.types.contract',
  INV: 'companyNumbering.types.invoice',
};

function patternToPresetId(pattern: string): string {
  return PRESETS.find((preset) => preset.pattern === pattern)?.id ?? 'custom';
}

/**
 * Company-Admin (settings.edit) org-admin zone: the document-numbering SCHEME — the token
 * mask, padding, reset period and start value that shape the company's КП / contract /
 * invoice numbers, plus the brand prefix. A custom scheme is only EFFECTIVE while the
 * company carries a prefix (the global-unique invariant) — surfaced as a non-blocking
 * banner. Numbers are server-minted (race-safe, gap-free); the preview is a live dry-run.
 */
export function CompanyNumberingSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);

  const companyId = user?.company?.id ?? user?.primary_company?.id ?? null;
  const canEditSettings = useHasCompanyPermission('settings.edit');

  const [prefix, setPrefix] = useState('');
  const [pattern, setPattern] = useState('');
  const [padding, setPadding] = useState(5);
  const [resetPeriod, setResetPeriod] = useState<NumberingResetPeriod>('yearly');
  const [startValue, setStartValue] = useState(0);

  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ['company-settings', companyId],
    queryFn: () => accountsApi.getCompanySettings(companyId as number),
    enabled: companyId != null && canEditSettings,
  });

  const { data: scheme, isLoading: schemeLoading } = useQuery({
    queryKey: ['numbering-scheme'],
    queryFn: () => crmApi.getNumberingScheme(),
    enabled: canEditSettings,
  });

  useEffect(() => {
    if (settings) setPrefix(settings.doc_number_prefix ?? '');
  }, [settings]);

  useEffect(() => {
    if (scheme) {
      setPattern(scheme.pattern);
      setPadding(scheme.padding);
      setResetPeriod(scheme.reset_period);
      setStartValue(scheme.start_value);
    }
  }, [scheme]);

  const presetId = patternToPresetId(pattern);
  const patternValid = pattern.trim() !== '' && pattern.includes('{seq}');

  // Live preview via the backend dry-run — the single source of truth for the number
  // FORMAT (uses the same token parser as real minting). Debounced so we fire one request
  // per pause, not per keystroke. The preview reflects the SAVED prefix (persist below to
  // brand it). We debounce a serialized key so the object identity churn doesn't reset it.
  const draft: NumberingSchemeUpdate = {
    pattern,
    padding,
    reset_period: resetPeriod,
    start_value: startValue,
  };
  const draftKey = JSON.stringify(draft);
  const debouncedKey = useDebouncedValue(draftKey, 350);
  const { data: preview } = useQuery({
    queryKey: ['numbering-preview', debouncedKey],
    queryFn: () => crmApi.previewNumberingScheme(JSON.parse(debouncedKey) as NumberingSchemeUpdate),
    enabled: canEditSettings && patternValid,
    placeholderData: (previous) => previous,
  });

  const saveMut = useMutation({
    mutationFn: async () => {
      const cleanPrefix = prefix.trim().slice(0, 16);
      // Persist the prefix (CompanySettings) only when it changed — it's the brand
      // discriminator that makes a custom scheme effective (global-unique invariant).
      if (companyId != null && cleanPrefix !== (settings?.doc_number_prefix ?? '').trim()) {
        await accountsApi.updateCompanySettings(companyId, { doc_number_prefix: cleanPrefix });
      }
      return crmApi.updateNumberingScheme(draft);
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(['numbering-scheme'], updated);
      queryClient.invalidateQueries({ queryKey: ['company-settings', companyId] });
      queryClient.invalidateQueries({ queryKey: ['numbering-preview'] });
      toast.success(t('companyNumbering.saved'));
    },
    onError: () => toast.error(t('common.error')),
  });

  if (!canEditSettings) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-border bg-muted/40 p-4">
        <Shield className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm font-medium text-muted-foreground">{t('companyNumbering.ownerOnly')}</p>
      </div>
    );
  }

  if (settingsLoading || schemeLoading) {
    return (
      <div className="flex p-10 justify-center" role="status">
        <Loader2 className="h-8 w-8 text-muted-foreground animate-spin" aria-hidden="true" />
        <span className="sr-only">{t('common.loading')}</span>
      </div>
    );
  }

  const prefixMissing = prefix.trim() === '';

  const selectPreset = (id: string) => {
    const preset = PRESETS.find((item) => item.id === id);
    if (preset) setPattern(preset.pattern);
  };

  // §2.4 reading-form pattern: section header left, form card right with a width cap.
  return (
    <div className="grid items-start gap-6 lg:grid-cols-[240px_1fr]">
      <div>
        <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
          <Hash className="h-5 w-5 text-primary" aria-hidden="true" />
          {t('companyNumbering.title')}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('companyNumbering.subtitle')}</p>
      </div>

      <Card className="min-w-0 max-w-2xl">
        <CardContent className="space-y-6">
          {/* Prefix — the brand discriminator. */}
          <div className="max-w-md space-y-2">
            <Label htmlFor="cn-prefix">{t('companyNumbering.prefix')}</Label>
            <Input
              id="cn-prefix"
              value={prefix}
              maxLength={16}
              onChange={(event) => setPrefix(event.target.value.replace(/[^A-Za-z0-9_-]/g, ''))}
              placeholder={t('companyNumbering.prefixPlaceholder')}
            />
            <p className="text-xs text-muted-foreground">{t('companyNumbering.prefixHelp')}</p>
          </div>

          {prefixMissing && (
            <div className="flex items-start gap-3 rounded-lg border border-info/40 bg-info/10 p-3">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-info" aria-hidden="true" />
              <p className="text-xs text-foreground">{t('companyNumbering.prefixlessBanner')}</p>
            </div>
          )}

          {/* Preset masks + custom. */}
          <div className="space-y-3">
            <Label>{t('companyNumbering.format')}</Label>
            <RadioGroup value={presetId} onValueChange={selectPreset} className="gap-2">
              {PRESETS.map((preset) => (
                <div key={preset.id} className="flex items-center gap-3">
                  <RadioGroupItem value={preset.id} id={`cn-preset-${preset.id}`} />
                  <Label htmlFor={`cn-preset-${preset.id}`} className="flex items-baseline gap-2 font-normal">
                    <span className="text-sm text-foreground">
                      {t(`companyNumbering.preset_${preset.id}`)}
                    </span>
                    <span className="font-mono text-xs text-muted-foreground">{t(preset.exampleKey)}</span>
                  </Label>
                </div>
              ))}
              <div className="flex items-center gap-3">
                <RadioGroupItem value="custom" id="cn-preset-custom" />
                <Label htmlFor="cn-preset-custom" className="font-normal text-sm text-foreground">
                  {t('companyNumbering.presetCustom')}
                </Label>
              </div>
            </RadioGroup>

            <div className="max-w-md space-y-2">
              <Label htmlFor="cn-mask">{t('companyNumbering.customMask')}</Label>
              <Input
                id="cn-mask"
                value={pattern}
                onChange={(event) => setPattern(event.target.value)}
                className="font-mono"
                aria-invalid={!patternValid}
              />
              <p className="text-xs text-muted-foreground">{t('companyNumbering.customMaskHelp')}</p>
              {!patternValid && (
                <p className="text-xs text-destructive">{t('companyNumbering.maskInvalid')}</p>
              )}
            </div>
          </div>

          {/* Padding / reset period / start value. */}
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="cn-padding">{t('companyNumbering.padding')}</Label>
              <Input
                id="cn-padding"
                type="number"
                min={1}
                max={20}
                value={padding}
                onChange={(event) => setPadding(Math.max(1, Math.min(20, Number(event.target.value) || 1)))}
              />
              <p className="text-xs text-muted-foreground">{t('companyNumbering.paddingHelp')}</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="cn-reset">{t('companyNumbering.resetPeriod')}</Label>
              <Select value={resetPeriod} onValueChange={(value) => setResetPeriod(value as NumberingResetPeriod)}>
                <SelectTrigger id="cn-reset">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RESET_PERIODS.map((period) => (
                    <SelectItem key={period} value={period}>
                      {t(`companyNumbering.resetOptions.${period}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="cn-start">{t('companyNumbering.startValue')}</Label>
              <Input
                id="cn-start"
                type="number"
                min={0}
                value={startValue}
                onChange={(event) => setStartValue(Math.max(0, Number(event.target.value) || 0))}
              />
              <p className="text-xs text-muted-foreground">{t('companyNumbering.startValueHelp')}</p>
            </div>
          </div>

          {/* Live preview — dry-run of 3 document kinds. */}
          <div className="rounded-lg border border-border bg-muted/40 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t('companyNumbering.previewLabel')}
            </p>
            <div className="mt-2 space-y-1.5">
              {patternValid && preview && preview.length > 0 ? (
                preview.map((item) => (
                  <div key={item.type_code} className="flex items-baseline gap-2">
                    <span className="w-24 shrink-0 text-xs text-muted-foreground">
                      {t(TYPE_LABEL_KEYS[item.type_code] ?? item.label)}
                    </span>
                    <span className="font-mono text-base font-semibold text-foreground">{item.number}</span>
                  </div>
                ))
              ) : (
                <p className="text-xs text-muted-foreground">{t('companyNumbering.previewUnavailable')}</p>
              )}
            </div>
          </div>
        </CardContent>

        <CardFooter>
          <Button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !patternValid}>
            {saveMut.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            {t('common.save')}
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

export default CompanyNumberingSettings;
