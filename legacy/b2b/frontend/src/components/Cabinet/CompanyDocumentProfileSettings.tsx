import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { FileText, Loader2, Shield } from 'lucide-react';

import { accountsApi, CompanyDocumentProfile } from '@/api/accountsApi';
import { useAuthStore } from '@/store/authStore';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { ImageUpload } from '@/components/Shared/ImageUpload';

type ProfileForm = {
  legal_name: string;
  inn: string;
  legal_address: string;
  bank_details: string;
  signatory_name: string;
  signatory_position: string;
  footer_text: string;
  accent_color: string;
};

const EMPTY_FORM: ProfileForm = {
  legal_name: '',
  inn: '',
  legal_address: '',
  bank_details: '',
  signatory_name: '',
  signatory_position: '',
  footer_text: '',
  accent_color: '',
};

function toForm(profile: CompanyDocumentProfile): ProfileForm {
  return {
    legal_name: profile.legal_name ?? '',
    inn: profile.inn ?? '',
    legal_address: profile.legal_address ?? '',
    bank_details: profile.bank_details ?? '',
    signatory_name: profile.signatory_name ?? '',
    signatory_position: profile.signatory_position ?? '',
    footer_text: profile.footer_text ?? '',
    accent_color: profile.accent_color ?? '',
  };
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
  const isOwner = user?.workspace_role === 'OWNER';

  const [form, setForm] = useState<ProfileForm>(EMPTY_FORM);

  const { data: profile, isLoading } = useQuery({
    queryKey: ['company-document-profile', companyId],
    queryFn: () => accountsApi.getCompanyDocumentProfile(companyId as number),
    enabled: companyId != null && isOwner,
  });

  useEffect(() => {
    if (profile) setForm(toForm(profile));
  }, [profile]);

  const saveMut = useMutation({
    mutationFn: (data: ProfileForm) =>
      accountsApi.updateCompanyDocumentProfile(companyId as number, data),
    onSuccess: (updated) => {
      queryClient.setQueryData(['company-document-profile', companyId], updated);
      toast.success(t('documentProfile.saved'));
    },
    onError: () => toast.error(t('common.error')),
  });

  if (!isOwner) {
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
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="flex items-center gap-2 text-xl font-bold text-foreground">
          <FileText className="h-5 w-5 text-primary" aria-hidden="true" />
          {t('documentProfile.title')}
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">{t('documentProfile.subtitle')}</p>
      </div>

      {companyId != null && (
        <ImageUpload
          value={profile?.logo_url ?? null}
          onUpload={handleLogoUpload}
          fallback={form.legal_name ? form.legal_name.slice(0, 2).toUpperCase() : '—'}
          label={t('documentProfile.logo')}
          description={t('documentProfile.logoDescription')}
        />
      )}

      <Separator />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-2 sm:col-span-2">
          <Label htmlFor="dp-legal-name">{t('documentProfile.legalName')}</Label>
          <Input
            id="dp-legal-name"
            value={form.legal_name}
            onChange={(e) => setForm({ ...form, legal_name: e.target.value })}
            placeholder={t('documentProfile.legalNamePlaceholder')}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="dp-inn">{t('documentProfile.inn')}</Label>
          <Input
            id="dp-inn"
            value={form.inn}
            onChange={(e) => setForm({ ...form, inn: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="dp-accent">{t('documentProfile.accentColor')}</Label>
          <div className="flex items-center gap-2">
            <Input
              id="dp-accent"
              value={form.accent_color}
              onChange={(e) => setForm({ ...form, accent_color: e.target.value })}
              placeholder="#15294d"
            />
            <Input
              type="color"
              aria-label={t('documentProfile.accentColor')}
              className="h-9 w-12 shrink-0 p-1"
              value={/^#[0-9a-fA-F]{6}$/.test(form.accent_color) ? form.accent_color : '#15294d'}
              onChange={(e) => setForm({ ...form, accent_color: e.target.value })}
            />
          </div>
        </div>
        <div className="space-y-2 sm:col-span-2">
          <Label htmlFor="dp-legal-address">{t('documentProfile.legalAddress')}</Label>
          <Textarea
            id="dp-legal-address"
            rows={2}
            value={form.legal_address}
            onChange={(e) => setForm({ ...form, legal_address: e.target.value })}
          />
        </div>
        <div className="space-y-2 sm:col-span-2">
          <Label htmlFor="dp-bank">{t('documentProfile.bankDetails')}</Label>
          <Textarea
            id="dp-bank"
            rows={3}
            value={form.bank_details}
            onChange={(e) => setForm({ ...form, bank_details: e.target.value })}
            placeholder={t('documentProfile.bankDetailsPlaceholder')}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="dp-signatory-name">{t('documentProfile.signatoryName')}</Label>
          <Input
            id="dp-signatory-name"
            value={form.signatory_name}
            onChange={(e) => setForm({ ...form, signatory_name: e.target.value })}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="dp-signatory-position">{t('documentProfile.signatoryPosition')}</Label>
          <Input
            id="dp-signatory-position"
            value={form.signatory_position}
            onChange={(e) => setForm({ ...form, signatory_position: e.target.value })}
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

      <Button onClick={() => saveMut.mutate(form)} disabled={saveMut.isPending}>
        {saveMut.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
        {t('common.save')}
      </Button>
    </div>
  );
}

export default CompanyDocumentProfileSettings;
