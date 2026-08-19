import { useDraftState } from '@/hooks/useDraftState';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Hash, Info, Loader2, Shield } from 'lucide-react';

import { accountsApi } from '@/api/accountsApi';
import { crmApi } from '@/api/crmApi';
import type { NumberingPreviewInput, NumberingResetPeriod, NumberingSchemeUpdate } from '@/api/crmApi';
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

// Backend {type} codes → localized «what kind» caption for the preview rows + editable
// type-label inputs. The VALUE printed in the number is company-editable (typeLabels state);
// this caption only NAMES the doc kind in the UI.
const TYPE_LABEL_KEYS: Record<string, string> = {
  KP: 'companyNumbering.types.quote',
  CT: 'companyNumbering.types.contract',
  INV: 'companyNumbering.types.invoice',
  ACT: 'companyNumbering.types.act',
  DOC: 'companyNumbering.types.doc',
};

// The editable {type}-label codes, in display order (mirrors backend NUMBERING_TYPE_CODES).
const TYPE_CODES = ['KP', 'CT', 'INV', 'ACT', 'DOC'] as const;

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

  // Поля пересобираются при смене загруженных данных прямо в рендере — без кадра с пустой формой.
  // Источник — КОМПАНИЯ, а не ссылка на ответ сервера. Пересборка по ответу затирала то, что
  // человек печатает: между нажатием «Сохранить» и ответом (замер: ~70–140 мс на localhost,
  // на реальной сети шире) правка молча пропадала, причём на экране в этот момент висел
  // зелёный тост «сохранено». Форму заполняем, когда данные ПРИШЛИ впервые или сменилась
  // компания; свои же сохранения её больше не трогают (найдено прогоном глазами 19-08).
  const [prefix, setPrefix] = useDraftState(
    settings ? `company:${companyId}` : null,
    () => settings?.doc_number_prefix ?? '',
  );
  const [schemeForm, setSchemeForm] = useDraftState(scheme ? 'loaded' : null, () => ({
    pattern: scheme?.pattern ?? '',
    padding: scheme?.padding ?? 5,
    resetPeriod: (scheme?.reset_period ?? 'yearly') as NumberingResetPeriod,
    startValue: scheme?.start_value ?? 0,
    typeLabels: scheme?.type_labels ?? {},
  }));
  const { pattern, padding, resetPeriod, startValue, typeLabels } = schemeForm;
  const setPattern = (value: string) => setSchemeForm((prev) => ({ ...prev, pattern: value }));
  const setPadding = (value: number) => setSchemeForm((prev) => ({ ...prev, padding: value }));
  const setResetPeriod = (value: NumberingResetPeriod) => setSchemeForm((prev) => ({ ...prev, resetPeriod: value }));
  const setStartValue = (value: number) => setSchemeForm((prev) => ({ ...prev, startValue: value }));
  const setLabelValue = (code: string, value: string) =>
    setSchemeForm((prev) => ({ ...prev, typeLabels: { ...prev.typeLabels, [code]: value } }));

  const presetId = patternToPresetId(pattern);
  const patternValid = pattern.trim() !== '' && pattern.includes('{seq}');

  const cleanPrefix = prefix.trim().slice(0, 16);

  // Live preview via the backend dry-run — the single source of truth for the number
  // FORMAT (uses the same token parser as real minting). Debounced so we fire one request
  // per pause, not per keystroke. The preview reflects the DRAFT prefix AND type labels
  // (WYSIWYG — no need to save first). We debounce a serialized key so object-identity
  // churn doesn't reset it.
  const draft: NumberingSchemeUpdate = {
    pattern,
    padding,
    reset_period: resetPeriod,
    start_value: startValue,
    type_labels: typeLabels,
  };
  const previewInput: NumberingPreviewInput = { ...draft, prefix: cleanPrefix };
  const previewKey = JSON.stringify(previewInput);
  const debouncedKey = useDebouncedValue(previewKey, 350);
  const { data: preview } = useQuery({
    queryKey: ['numbering-preview', debouncedKey],
    queryFn: () => crmApi.previewNumberingScheme(JSON.parse(debouncedKey) as NumberingPreviewInput),
    // Ждём, пока ОТЛОЖЕННЫЙ ключ догонит текущий ввод. Иначе на открытии экрана уходил запрос
    // со ВЧЕРАШНИМ ключом: маска приходит с сервера и делает `patternValid` истинным раньше,
    // чем отпустит debounce, — превью просилось с пустой маской и падало 400 ERR_BAD_REQUEST
    // красным тостом прямо в лицо. Найдено прогоном глазами 18-08.
    enabled: canEditSettings && patternValid && debouncedKey === previewKey,
    placeholderData: (previous) => previous,
  });

  const saveMut = useMutation({
    mutationFn: async () => {
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

  const setLabel = setLabelValue;

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

          {/* Editable {type}-token label per doc kind — nothing hardcoded; the company
              decides what «КП/Договор/Инвойс/Акт/Документ» prints as in its numbers. */}
          <div className="space-y-3">
            <div>
              <Label>{t('companyNumbering.typeLabelsTitle')}</Label>
              <p className="mt-1 text-xs text-muted-foreground">{t('companyNumbering.typeLabelsHelp')}</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {TYPE_CODES.map((code) => (
                <div key={code} className="space-y-1.5">
                  <Label htmlFor={`cn-type-${code}`} className="text-xs font-normal text-muted-foreground">
                    {t(TYPE_LABEL_KEYS[code])}
                  </Label>
                  <Input
                    id={`cn-type-${code}`}
                    value={typeLabels[code] ?? ''}
                    maxLength={32}
                    onChange={(event) => setLabel(code, event.target.value)}
                    className="font-mono"
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Live preview — dry-run of every editable document kind. */}
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
