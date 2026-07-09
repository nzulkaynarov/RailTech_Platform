import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Save } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';

import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { useUserStore, companyStatusLabels } from '@/store/userStore';
import { useAuthStore } from '@/store/authStore';
import { useCountries } from '@/hooks/useMasterData';
import { accountsApi, type KYCDocument, type Company } from '@/api/accountsApi';
import { toast } from 'sonner';
import { ImageUpload } from '@/components/Shared/ImageUpload';
import { FileUpload } from '@/components/Shared/FileUpload';


export function CompanyTab() {
  const { t } = useTranslation();
  const { company, activeStatus, updateCompany } = useUserStore();
  const workspaceRole = useAuthStore((s) => s.user?.workspace_role ?? null);
  const isViewerMode = useUserStore((s) => s.isViewerMode);
  // Editing the company profile is an OWNER action (platform admin may also edit).
  const canEdit = isViewerMode || workspaceRole === 'OWNER';
  // INN is locked once KYC is verified — it becomes a checked legal identifier.
  const innLocked = company.kycStatus === 'verified';

  const { data: countries = [] } = useCountries();

  const companyId = company.id;
  const [savingCompany, setSavingCompany] = useState(false);
  const [docs, setDocs] = useState<KYCDocument[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [cForm, setCForm] = useState({
    name: company.name, inn: company.inn, contact_person: '', phone: '', email: '',
    website: '', legal_address: '', bank_account: '', mfo: '',
    country: '' as number | string, has_iso9001: false,
  });

  // The /me/ company is a lightweight projection (no contacts/requisites).
  // Pull the full record so every editable field is populated, not blanked.
  useEffect(() => {
    if (!companyId) return;
    setLoadingDocs(true);
    accountsApi.getCompanyDetail(companyId)
      .then((c) => {
        setDocs(c.kyc_documents ?? []);
        setCForm({
          name: c.name ?? '', inn: c.inn ?? '', contact_person: c.contact_person ?? '',
          phone: c.phone ?? '', email: c.email ?? '', website: c.website ?? '',
          legal_address: c.legal_address ?? '', bank_account: c.bank_account ?? '',
          mfo: c.mfo ?? '', country: c.country ?? '', has_iso9001: !!c.has_iso9001,
        });
      })
      .catch(() => toast.error(t('profile.companyInfo.docsLoadError')))
      .finally(() => setLoadingDocs(false));
  }, [companyId, t]);

  const kycBadge = company.kycStatus === 'verified'
    ? { variant: 'default' as const, label: t('profile.companyInfo.kycVerified'), className: '' }
    : { variant: 'secondary' as const, label: t('profile.companyInfo.kycPending'), className: 'text-warning' };

  const handleSaveCompany = async () => {
    if (!companyId) {
      toast.error(t('common.error'));
      return;
    }
    setSavingCompany(true);
    try {
      const payload: Partial<Company> = {
        name: cForm.name,
        contact_person: cForm.contact_person,
        phone: cForm.phone,
        email: cForm.email,
        website: cForm.website,
        legal_address: cForm.legal_address,
        bank_account: cForm.bank_account,
        mfo: cForm.mfo,
        country: cForm.country === '' ? null : Number(cForm.country),
        has_iso9001: cForm.has_iso9001,
      };
      if (!innLocked) payload.inn = cForm.inn;
      await accountsApi.updateCompany(companyId, payload);
      updateCompany({ name: cForm.name });
      toast.success(t('profile.companyInfo.saved'));
    } catch {
      toast.error(t('common.error'));
    } finally {
      setSavingCompany(false);
    }
  };

  const handleLogoUpload = async (file: File) => {
    if (!companyId) throw new Error('NO_COMPANY');
    const updated = await accountsApi.uploadCompanyLogo(companyId, file);
    updateCompany({ logoUrl: updated.logo ?? null });
  };

  const handleLogoRemove = async () => {
    if (!companyId) return;
    await accountsApi.deleteCompanyLogo(companyId);
    updateCompany({ logoUrl: null });
  };

  const handleDocUpload = async (file: File) => {
    if (!companyId) throw new Error('NO_COMPANY');
    const doc = await accountsApi.uploadDocument(companyId, file, 'OTHER');
    setDocs(prev => [doc, ...prev]);
  };

  const handleDocRemove = async (id: string | number) => {
    if (!companyId) return;
    await accountsApi.deleteDocument(companyId, Number(id));
    setDocs(prev => prev.filter(d => d.id !== id));
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t('profile.companyInfo.title')}</CardTitle>
        <CardDescription>{t('profile.companyInfo.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {companyId && (
          <ImageUpload
            value={company.logoUrl}
            onUpload={handleLogoUpload}
            onRemove={handleLogoRemove}
            fallback={company.name ? company.name.slice(0, 2).toUpperCase() : '—'}
            label={t('profile.companyInfo.logo')}
            description={t('profile.companyInfo.logoDescription')}
          />
        )}

        <Separator />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label>{t('profile.companyInfo.name')}</Label>
            <Input value={cForm.name} onChange={(e) => setCForm({ ...cForm, name: e.target.value })} disabled={!canEdit} />
          </div>
          <div className="space-y-2">
            <Label>{t('profile.companyInfo.inn')}</Label>
            <Input value={cForm.inn} onChange={(e) => setCForm({ ...cForm, inn: e.target.value })} disabled={!canEdit || innLocked} />
          </div>
          <div className="space-y-2">
            <Label>{t('profile.companyInfo.contactPerson')}</Label>
            <Input value={cForm.contact_person} onChange={(e) => setCForm({ ...cForm, contact_person: e.target.value })} disabled={!canEdit} />
          </div>
          <div className="space-y-2">
            <Label>{t('profile.companyInfo.phone')}</Label>
            <Input value={cForm.phone} onChange={(e) => setCForm({ ...cForm, phone: e.target.value })} disabled={!canEdit} />
          </div>
          <div className="space-y-2">
            <Label>{t('profile.companyInfo.email')}</Label>
            <Input type="email" value={cForm.email} onChange={(e) => setCForm({ ...cForm, email: e.target.value })} disabled={!canEdit} />
          </div>
          <div className="space-y-2">
            <Label>{t('profile.companyInfo.website')}</Label>
            <Input value={cForm.website} onChange={(e) => setCForm({ ...cForm, website: e.target.value })} disabled={!canEdit} />
          </div>
          <div className="space-y-2">
            <Label>{t('profile.companyInfo.country')}</Label>
            <Select
              value={cForm.country ? String(cForm.country) : undefined}
              onValueChange={(v) => setCForm({ ...cForm, country: v })}
              disabled={!canEdit}
            >
              <SelectTrigger><SelectValue placeholder={t('profile.companyInfo.countryPlaceholder')} /></SelectTrigger>
              <SelectContent>
                {countries.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>{t('profile.companyInfo.bankAccount')}</Label>
            <Input value={cForm.bank_account} onChange={(e) => setCForm({ ...cForm, bank_account: e.target.value })} disabled={!canEdit} />
          </div>
          <div className="space-y-2">
            <Label>{t('profile.companyInfo.mfo')}</Label>
            <Input value={cForm.mfo} onChange={(e) => setCForm({ ...cForm, mfo: e.target.value })} disabled={!canEdit} />
          </div>
          <div className="space-y-2 sm:col-span-2">
            <Label>{t('profile.companyInfo.legalAddress')}</Label>
            <Textarea value={cForm.legal_address} onChange={(e) => setCForm({ ...cForm, legal_address: e.target.value })} disabled={!canEdit} rows={2} />
          </div>
          <div className="flex items-center justify-between rounded-lg border p-3 sm:col-span-2">
            <div className="space-y-0.5">
              <Label htmlFor="iso9001">{t('profile.companyInfo.iso9001')}</Label>
              <p className="text-xs text-muted-foreground">{t('profile.companyInfo.iso9001Help')}</p>
            </div>
            <Switch id="iso9001" checked={cForm.has_iso9001} onCheckedChange={(v) => setCForm({ ...cForm, has_iso9001: v })} disabled={!canEdit} />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Label>{t('profile.companyInfo.kycStatus')}:</Label>
          <Badge variant={kycBadge.variant} className={kycBadge.className}>{kycBadge.label}</Badge>
        </div>

        <Separator />

        <div className="space-y-2">
          <Label>{t('profile.companyInfo.platformStatuses')}</Label>
          <div className="flex flex-wrap gap-2">
            {company.statusEntries.map((entry) => (
              <Badge key={entry.status} variant={entry.status === activeStatus ? 'default' : 'outline'}>
                {t(companyStatusLabels[entry.status])}
                {entry.verification === 'pending' && ` (${t('profile.companyInfo.pendingVerification')})`}
              </Badge>
            ))}
          </div>
        </div>

        {companyId && (
          <>
            <Separator />
            <div>
              <Label className="text-sm font-medium">{t('profile.companyInfo.kycDocuments')}</Label>
              <FileUpload
                className="mt-2"
                disabled={loadingDocs}
                files={docs.map(d => ({
                  id: d.id,
                  name: d.doc_type_display
                    ? `${d.doc_type_display} — ${d.original_filename}`
                    : d.original_filename,
                  url: d.file ?? null,
                  uploaded_at: d.uploaded_at,
                }))}
                onUpload={handleDocUpload}
                onRemove={handleDocRemove}
                description={t('profile.companyInfo.kycDocumentsHelp')}
              />
            </div>
          </>
        )}

        {canEdit && (
          <div className="flex justify-end">
            <Button onClick={handleSaveCompany} disabled={savingCompany} className="gap-2">
              <Save className="h-4 w-4" />
              {savingCompany ? t('common.saving') : t('profile.companyInfo.save')}
            </Button>
          </div>
        )}

        {!canEdit && (
          <p className="text-xs text-muted-foreground">
            {t('profile.companyInfo.contactAdmin')}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

