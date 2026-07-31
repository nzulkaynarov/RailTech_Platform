import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { FileText, Loader2, Lock, Shield } from 'lucide-react';

import {
  accountsApi,
  CompanyDocumentProfile,
  DocumentFontFamily,
  DocumentLayoutPreset,
  DocumentPreviewType,
} from '@/api/accountsApi';
import { useAuthStore } from '@/store/authStore';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from '@/components/ui/tooltip';
import { ImageUpload } from '@/components/Shared/ImageUpload';

// Brand-default accent color of the generated КП/contract PDF (mirrors the backend
// document default). This is a PDF-document brand value, NOT a UI color token —
// named here so the placeholder and the color-picker fallback stay in sync.
const PDF_ACCENT_COLOR_DEFAULT = '#15294d';
// Backend default secondary (panel/zebra) tint — same rationale as the accent default.
const PDF_SECONDARY_COLOR_DEFAULT = '#f6f8fb';

// Mirror backend LAYOUT_CHOICES / FONT_CHOICES / PREVIEW_DOC_TYPES (codes, Rule 2).
const LAYOUT_PRESETS: DocumentLayoutPreset[] = ['light', 'boxed', 'bold', 'striped'];
const FONT_FAMILIES: DocumentFontFamily[] = ['sans', 'serif'];
const PREVIEW_TYPES: DocumentPreviewType[] = ['KP', 'CT', 'INV', 'ACT', 'DOC'];

type ProfileForm = {
  use_company_defaults: boolean;
  legal_name: string;
  inn: string;
  legal_address: string;
  bank_details: string;
  signatory_name: string;
  signatory_position: string;
  footer_text: string;
  accent_color: string;
  secondary_color: string;
  layout_preset: DocumentLayoutPreset;
  font_family: DocumentFontFamily;
  cover_letter_text: string;
  contract_acceptance_text: string;
  contract_liability_text: string;
  contract_extra_terms_text: string;
  act_closing_text: string;
  show_cover_letter: boolean;
  show_bank_in_header: boolean;
  show_logo: boolean;
  show_lead_time: boolean;
  show_fx_note: boolean;
};

const EMPTY_FORM: ProfileForm = {
  use_company_defaults: true,
  legal_name: '',
  inn: '',
  legal_address: '',
  bank_details: '',
  signatory_name: '',
  signatory_position: '',
  footer_text: '',
  accent_color: '',
  secondary_color: '',
  layout_preset: 'light',
  font_family: 'sans',
  cover_letter_text: '',
  contract_acceptance_text: '',
  contract_liability_text: '',
  contract_extra_terms_text: '',
  act_closing_text: '',
  show_cover_letter: false,
  show_bank_in_header: true,
  show_logo: true,
  show_lead_time: true,
  show_fx_note: false,
};

function toForm(profile: CompanyDocumentProfile): ProfileForm {
  return {
    use_company_defaults: profile.use_company_defaults ?? true,
    legal_name: profile.legal_name ?? '',
    inn: profile.inn ?? '',
    legal_address: profile.legal_address ?? '',
    bank_details: profile.bank_details ?? '',
    signatory_name: profile.signatory_name ?? '',
    signatory_position: profile.signatory_position ?? '',
    footer_text: profile.footer_text ?? '',
    accent_color: profile.accent_color ?? '',
    secondary_color: profile.secondary_color ?? '',
    layout_preset: profile.layout_preset ?? 'light',
    font_family: profile.font_family ?? 'sans',
    cover_letter_text: profile.cover_letter_text ?? '',
    contract_acceptance_text: profile.contract_acceptance_text ?? '',
    contract_liability_text: profile.contract_liability_text ?? '',
    contract_extra_terms_text: profile.contract_extra_terms_text ?? '',
    act_closing_text: profile.act_closing_text ?? '',
    show_cover_letter: profile.show_cover_letter ?? false,
    show_bank_in_header: profile.show_bank_in_header ?? true,
    show_logo: profile.show_logo ?? true,
    show_lead_time: profile.show_lead_time ?? true,
    show_fx_note: profile.show_fx_note ?? false,
  };
}

/**
 * Lock marker + tooltip next to labels of fields inherited from the company profile
 * (spec §2.5: disabled inputs + Lock icon + Tooltip instead of opacity/pointer-events).
 */
function InheritedLockHint({ hint }: { hint: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0} className="inline-flex text-muted-foreground">
          <Lock className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="sr-only">{hint}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>{hint}</TooltipContent>
    </Tooltip>
  );
}

/**
 * Company-Admin (OWNER) org-admin zone: edit the company Document Profile printed
 * on the КП / contract PDFs (logo, legal block, signatory, footer, accent color).
 * The seller's profile feeds the «Поставщик» block on the client КП document.
 */
export function CompanyDocumentProfileSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const user = useAuthStore((s) => s.user);

  const companyId = user?.company?.id ?? user?.primary_company?.id ?? null;
  const canEditSettings = useHasCompanyPermission('settings.edit');

  const [form, setForm] = useState<ProfileForm>(EMPTY_FORM);
  const [previewType, setPreviewType] = useState<DocumentPreviewType>('KP');

  const { data: profile, isLoading } = useQuery({
    queryKey: ['company-document-profile', companyId],
    queryFn: () => accountsApi.getCompanyDocumentProfile(companyId as number),
    enabled: companyId != null && canEditSettings,
  });

  useEffect(() => {
    if (profile) setForm(toForm(profile));
  }, [profile]);

  // Live WYSIWYG preview (Odoo Document-Layout wizard): the CURRENT form state overlays the
  // saved profile in-memory server-side, so every unsaved edit (accent, layout, font…) shows
  // immediately, on ANY of the 5 document kinds. Debounced via a serialized key so object
  // identity churn doesn't refire per keystroke.
  const previewKey = useDebouncedValue(JSON.stringify({ t: previewType, d: form }), 400);
  const previewQuery = useQuery({
    queryKey: ['company-document-profile-preview', companyId, previewKey],
    queryFn: () => {
      const parsed = JSON.parse(previewKey) as { t: DocumentPreviewType; d: ProfileForm };
      return accountsApi.previewCompanyDocumentProfile(companyId as number, {
        doc_type: parsed.t,
        draft: parsed.d,
      });
    },
    enabled: companyId != null && canEditSettings,
    placeholderData: (previous) => previous,
  });

  const saveMut = useMutation({
    mutationFn: (data: ProfileForm) =>
      accountsApi.updateCompanyDocumentProfile(companyId as number, data),
    onSuccess: (updated) => {
      queryClient.setQueryData(['company-document-profile', companyId], updated);
      toast.success(t('documentProfile.saved'));
    },
    onError: () => toast.error(t('common.error')),
  });

  if (!canEditSettings) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-border bg-muted/40 p-4">
        <Shield className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm font-medium text-muted-foreground">{t('documentProfile.ownerOnly')}</p>
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

  const handleLogoUpload = async (file: File) => {
    if (companyId == null) throw new Error('NO_COMPANY');
    const updated = await accountsApi.uploadCompanyDocumentLogo(companyId, file);
    queryClient.setQueryData(['company-document-profile', companyId], updated);
    queryClient.invalidateQueries({ queryKey: ['company-document-profile-preview', companyId] });
  };

  const toggleRow = (
    key: 'show_logo' | 'show_lead_time' | 'show_fx_note' | 'show_cover_letter' | 'show_bank_in_header',
    labelKey: string,
    descKey: string,
  ) => (
    <div className="flex items-start justify-between gap-4 rounded-lg border border-border p-3">
      <div className="space-y-0.5">
        <Label htmlFor={`dp-${key}`} className="cursor-pointer">{t(labelKey)}</Label>
        <p className="text-xs text-muted-foreground">{t(descKey)}</p>
      </div>
      <Switch
        id={`dp-${key}`}
        checked={form[key]}
        onCheckedChange={(v) => setForm({ ...form, [key]: v })}
      />
    </div>
  );

  // Fields inherited from the company profile while «use company defaults» is on (§2.5):
  // disabled + Lock/Tooltip, never opacity/pointer-events hacks.
  const inherited = form.use_company_defaults;
  const inheritedHint = t('settings.documents.inheritedFromCompany');

  return (
    <TooltipProvider>
      <div className="space-y-6">
        <div>
          <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
            <FileText className="h-5 w-5 text-primary" aria-hidden="true" />
            {t('documentProfile.title')}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">{t('documentProfile.subtitle')}</p>
        </div>

        {/* Form and preview side-by-side on desktop (spec PR 3, §2.4): even two-column split;
            the A4 preview fills its whole column — previews are never width-capped. */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="space-y-6">
            <div className="flex items-start justify-between gap-4 rounded-lg border border-border p-3 bg-muted/30">
              <div className="space-y-0.5">
                <Label htmlFor="dp-use-company-defaults" className="cursor-pointer">
                  {t('documentProfile.useCompanyDefaults')}
                </Label>
                <p className="text-xs text-muted-foreground">
                  {t('documentProfile.useCompanyDefaultsHint')}
                </p>
              </div>
              <Switch
                id="dp-use-company-defaults"
                checked={form.use_company_defaults}
                onCheckedChange={(v) => {
                  setForm({ ...form, use_company_defaults: v });
                }}
              />
            </div>

            {companyId != null && (
              <div className="space-y-2">
                <div className="flex items-center gap-1.5">
                  <Label>{t('documentProfile.logo')}</Label>
                  {inherited && <InheritedLockHint hint={inheritedHint} />}
                </div>
                <ImageUpload
                  value={profile?.logo_url ?? null}
                  onUpload={handleLogoUpload}
                  disabled={inherited}
                  fallback={form.legal_name ? form.legal_name.slice(0, 2).toUpperCase() : '—'}
                  description={t('documentProfile.logoDescription')}
                />
              </div>
            )}

            <Separator />

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="dp-legal-name" className="gap-1.5">
                  {t('documentProfile.legalName')}
                  {inherited && <InheritedLockHint hint={inheritedHint} />}
                </Label>
                <Input
                  id="dp-legal-name"
                  value={form.legal_name}
                  onChange={(e) => setForm({ ...form, legal_name: e.target.value })}
                  placeholder={t('documentProfile.legalNamePlaceholder')}
                  disabled={inherited}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="dp-inn" className="gap-1.5">
                  {t('documentProfile.inn')}
                  {inherited && <InheritedLockHint hint={inheritedHint} />}
                </Label>
                <Input
                  id="dp-inn"
                  value={form.inn}
                  onChange={(e) => setForm({ ...form, inn: e.target.value })}
                  disabled={inherited}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="dp-accent">{t('documentProfile.accentColor')}</Label>
                <div className="flex items-center gap-2">
                  <Input
                    id="dp-accent"
                    value={form.accent_color}
                    onChange={(e) => setForm({ ...form, accent_color: e.target.value })}
                    placeholder={PDF_ACCENT_COLOR_DEFAULT}
                  />
                  <Input
                    type="color"
                    aria-label={t('documentProfile.accentColor')}
                    className="h-9 w-12 shrink-0 p-1"
                    value={/^#[0-9a-fA-F]{6}$/.test(form.accent_color) ? form.accent_color : PDF_ACCENT_COLOR_DEFAULT}
                    onChange={(e) => setForm({ ...form, accent_color: e.target.value })}
                  />
                </div>
              </div>
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="dp-legal-address" className="gap-1.5">
                  {t('documentProfile.legalAddress')}
                  {inherited && <InheritedLockHint hint={inheritedHint} />}
                </Label>
                <Textarea
                  id="dp-legal-address"
                  rows={2}
                  value={form.legal_address}
                  onChange={(e) => setForm({ ...form, legal_address: e.target.value })}
                  disabled={inherited}
                />
              </div>
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="dp-bank" className="gap-1.5">
                  {t('documentProfile.bankDetails')}
                  {inherited && <InheritedLockHint hint={inheritedHint} />}
                </Label>
                <Textarea
                  id="dp-bank"
                  rows={3}
                  value={form.bank_details}
                  onChange={(e) => setForm({ ...form, bank_details: e.target.value })}
                  placeholder={t('documentProfile.bankDetailsPlaceholder')}
                  disabled={inherited}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="dp-signatory-name" className="gap-1.5">
                  {t('documentProfile.signatoryName')}
                  {inherited && <InheritedLockHint hint={inheritedHint} />}
                </Label>
                <Input
                  id="dp-signatory-name"
                  value={form.signatory_name}
                  onChange={(e) => setForm({ ...form, signatory_name: e.target.value })}
                  disabled={inherited}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="dp-signatory-position" className="gap-1.5">
                  {t('documentProfile.signatoryPosition')}
                  {inherited && <InheritedLockHint hint={inheritedHint} />}
                </Label>
                <Input
                  id="dp-signatory-position"
                  value={form.signatory_position}
                  onChange={(e) => setForm({ ...form, signatory_position: e.target.value })}
                  disabled={inherited}
                />
              </div>
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="dp-footer">{t('documentProfile.footerText')}</Label>
                <Textarea
                  id="dp-footer"
                  rows={2}
                  value={form.footer_text}
                  onChange={(e) => setForm({ ...form, footer_text: e.target.value })}
                  placeholder={t('documentProfile.footerTextPlaceholder')}
                />
              </div>
            </div>

            <Separator />
            {/* D2 document theme (Odoo Document Layout): one theme drives ALL the company's
                PDFs — layout preset, font pair, secondary tint. Applied live in the preview. */}
            <div className="space-y-4">
              <div>
                <h4 className="text-sm font-semibold text-foreground">{t('documentProfile.themeTitle')}</h4>
                <p className="mt-0.5 text-xs text-muted-foreground">{t('documentProfile.themeHint')}</p>
              </div>
              <div className="space-y-2">
                <Label>{t('documentProfile.layoutPreset')}</Label>
                <RadioGroup
                  value={form.layout_preset}
                  onValueChange={(v) => setForm({ ...form, layout_preset: v as DocumentLayoutPreset })}
                  className="grid grid-cols-2 gap-2"
                >
                  {LAYOUT_PRESETS.map((preset) => (
                    <Label
                      key={preset}
                      htmlFor={`dp-layout-${preset}`}
                      className="flex cursor-pointer items-start gap-2 rounded-lg border border-border p-3 font-normal has-[button[data-state=checked]]:border-primary"
                    >
                      <RadioGroupItem value={preset} id={`dp-layout-${preset}`} className="mt-0.5" />
                      <span className="space-y-0.5">
                        <span className="block text-sm font-medium text-foreground">
                          {t(`documentProfile.layouts.${preset}`)}
                        </span>
                        <span className="block text-xs text-muted-foreground">
                          {t(`documentProfile.layouts.${preset}Hint`)}
                        </span>
                      </span>
                    </Label>
                  ))}
                </RadioGroup>
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="dp-font">{t('documentProfile.fontFamily')}</Label>
                  <Select
                    value={form.font_family}
                    onValueChange={(v) => setForm({ ...form, font_family: v as DocumentFontFamily })}
                  >
                    <SelectTrigger id="dp-font">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {FONT_FAMILIES.map((font) => (
                        <SelectItem key={font} value={font}>
                          {t(`documentProfile.fonts.${font}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="dp-secondary">{t('documentProfile.secondaryColor')}</Label>
                  <div className="flex items-center gap-2">
                    <Input
                      id="dp-secondary"
                      value={form.secondary_color}
                      onChange={(e) => setForm({ ...form, secondary_color: e.target.value })}
                      placeholder={PDF_SECONDARY_COLOR_DEFAULT}
                    />
                    <Input
                      type="color"
                      aria-label={t('documentProfile.secondaryColor')}
                      className="h-9 w-12 shrink-0 p-1"
                      value={/^#[0-9a-fA-F]{6}$/.test(form.secondary_color) ? form.secondary_color : PDF_SECONDARY_COLOR_DEFAULT}
                      onChange={(e) => setForm({ ...form, secondary_color: e.target.value })}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">{t('documentProfile.secondaryColorHint')}</p>
                </div>
              </div>
            </div>

            <Separator />
            {/* spec-kp-blank: cover-letter paragraph («КП + письмо в одном») + bank-in-header. */}
            <div className="space-y-4">
              <div>
                <h4 className="text-sm font-semibold text-foreground">{t('documentProfile.blankTitle')}</h4>
                <p className="mt-0.5 text-xs text-muted-foreground">{t('documentProfile.blankHint')}</p>
              </div>
              {toggleRow('show_bank_in_header', 'documentProfile.showBankInHeader', 'documentProfile.showBankInHeaderHint')}
              {toggleRow('show_cover_letter', 'documentProfile.showCoverLetter', 'documentProfile.showCoverLetterHint')}
              {form.show_cover_letter && (
                <div className="space-y-2">
                  <Label htmlFor="dp-cover">{t('documentProfile.coverText')}</Label>
                  <Textarea
                    id="dp-cover"
                    rows={4}
                    value={form.cover_letter_text}
                    onChange={(e) => setForm({ ...form, cover_letter_text: e.target.value })}
                    placeholder={t('documentProfile.coverTextPlaceholder')}
                  />
                  <p className="text-xs text-muted-foreground">{t('documentProfile.coverTextTokens')}</p>
                </div>
              )}
            </div>

            <Separator />
            {/* Формулировки документов: каркас (таблица, итоги, реквизиты, подписи) остаётся
                кодом, а проза — данными. Так границу проводят эталоны отчётов: настраиваемый
                текст живёт в полях, структура — в шаблоне. Пустое поле печатает платформенную
                формулировку, поэтому ничего не заполнивший получает прежний документ. */}
            <div className="space-y-4">
              <div>
                <h4 className="text-sm font-semibold text-foreground">{t('documentProfile.wording.title')}</h4>
                <p className="mt-0.5 text-xs text-muted-foreground">{t('documentProfile.wording.hint')}</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="dp-contract-acceptance-text">{t('documentProfile.wording.contractAcceptance')}</Label>
                <Textarea
                  id="dp-contract-acceptance-text"
                  rows={4}
                  value={form.contract_acceptance_text}
                  onChange={(e) => setForm({ ...form, contract_acceptance_text: e.target.value })}
                />
                <p className="text-xs text-muted-foreground">{t('documentProfile.wording.contractAcceptanceHint')}</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="dp-contract-liability-text">{t('documentProfile.wording.contractLiability')}</Label>
                <Textarea
                  id="dp-contract-liability-text"
                  rows={4}
                  value={form.contract_liability_text}
                  onChange={(e) => setForm({ ...form, contract_liability_text: e.target.value })}
                />
                <p className="text-xs text-muted-foreground">{t('documentProfile.wording.contractLiabilityHint')}</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="dp-contract-extra-terms-text">{t('documentProfile.wording.contractExtra')}</Label>
                <Textarea
                  id="dp-contract-extra-terms-text"
                  rows={4}
                  value={form.contract_extra_terms_text}
                  onChange={(e) => setForm({ ...form, contract_extra_terms_text: e.target.value })}
                />
                <p className="text-xs text-muted-foreground">{t('documentProfile.wording.contractExtraHint')}</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="dp-act-closing-text">{t('documentProfile.wording.actClosing')}</Label>
                <Textarea
                  id="dp-act-closing-text"
                  rows={4}
                  value={form.act_closing_text}
                  onChange={(e) => setForm({ ...form, act_closing_text: e.target.value })}
                />
                <p className="text-xs text-muted-foreground">{t('documentProfile.wording.actClosingHint')}</p>
              </div>
            </div>

            <Separator />
            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-foreground">{t('documentProfile.toggles')}</h4>
              {toggleRow('show_logo', 'documentProfile.showLogo', 'documentProfile.showLogoHint')}
              {toggleRow('show_lead_time', 'documentProfile.showLeadTime', 'documentProfile.showLeadTimeHint')}
              {toggleRow('show_fx_note', 'documentProfile.showFxNote', 'documentProfile.showFxNoteHint')}
            </div>

            <Button onClick={() => saveMut.mutate(form)} disabled={saveMut.isPending}>
              {saveMut.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {t('common.save')}
            </Button>
          </div>

          <div className="space-y-2 lg:sticky lg:top-4 lg:self-start">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-semibold text-foreground">{t('documentProfile.preview')}</h4>
              {previewQuery.isFetching && (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" />
              )}
            </div>
            <p className="text-xs text-muted-foreground">{t('documentProfile.previewHint')}</p>
            {/* Preview any of the 5 document kinds — the ONE theme applies to all (D1b). */}
            <Tabs value={previewType} onValueChange={(v) => setPreviewType(v as DocumentPreviewType)}>
              <TabsList className="w-full">
                {PREVIEW_TYPES.map((docType) => (
                  <TabsTrigger key={docType} value={docType} className="flex-1">
                    {t(`documentProfile.previewTypes.${docType}`)}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            {/* allow-same-origin lets Chrome actually PAINT the srcDoc (an opaque-origin
                sandbox="" renders blank); scripts stay blocked (no allow-scripts) so any markup
                a seller injects into their requisites can't execute in the preview.
                bg-white is intentional (justified Rule 4 exception): the iframe shows the A4
                КП document and paper is white in BOTH UI themes — a semantic token would
                tint the "paper" in dark mode. */}
            <iframe
              title={t('documentProfile.preview')}
              srcDoc={previewQuery.data ?? ''}
              sandbox="allow-same-origin"
              className="h-[70vh] w-full rounded-lg border border-border bg-white"
            />
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}

export default CompanyDocumentProfileSettings;
