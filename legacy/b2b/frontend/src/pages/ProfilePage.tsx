import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Shield, Save, KeyRound } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';

import { useUserStore, roleLabels, companyStatusLabels } from '@/store/userStore';
import { useAuthStore } from '@/store/authStore';
import { useCountries } from '@/hooks/useMasterData';
import { accountsApi, type KYCDocument, type Company } from '@/api/accountsApi';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { ImageUpload } from '@/components/Shared/ImageUpload';
import { FileUpload } from '@/components/Shared/FileUpload';

function PasswordChangeForm({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [changingPw, setChangingPw] = useState(false);

  const handleChangePassword = async () => {
    if (newPassword !== confirmPassword) {
      toast.error(t('profile.passwordDialog.mismatch'));
      return;
    }
    setChangingPw(true);
    try {
      await accountsApi.changePassword({ current_password: currentPassword, new_password: newPassword });
      toast.success(t('profile.passwordDialog.success'));
      onClose();
    } catch (e) {
      // Surface the backend's specific reason (wrong current password, weak
      // password, …) instead of a generic message.
      toast.error(translateApiError(e));
    } finally {
      setChangingPw(false);
    }
  };

  return (
    <>
      <div className="space-y-4 py-2">
        <div className="space-y-2">
          <Label>{t('profile.passwordDialog.currentPassword')}</Label>
          <Input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label>{t('profile.passwordDialog.newPassword')}</Label>
          <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label>{t('profile.passwordDialog.confirmPassword')}</Label>
          <Input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
        <Button onClick={handleChangePassword} disabled={changingPw || !currentPassword || !newPassword}>
          {changingPw ? t('common.saving') : t('common.save')}
        </Button>
      </DialogFooter>
    </>
  );
}

function CompanyTab() {
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

export function ProfilePage() {
  const { t } = useTranslation();
  const { profile, role, updateProfile } = useUserStore();
  const [form, setForm] = useState({ ...profile });
  const [saving, setSaving] = useState(false);
  const [passwordDialog, setPasswordDialog] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await accountsApi.updateMe({
        first_name: form.firstName,
        last_name: form.lastName,
        phone: form.phone,
        position: form.position,
      });
      updateProfile(form);
      toast.success(t('profile.personalInfo.saved'));
    } catch {
      toast.error(t('profile.personalInfo.saveError'));
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarUpload = async (file: File) => {
    const updated = await accountsApi.uploadAvatar(file);
    updateProfile({ avatarUrl: updated.avatar ?? null });
  };
  const handleAvatarRemove = async () => {
    await accountsApi.deleteAvatar();
    updateProfile({ avatarUrl: null });
  };


  return (
    <div className="flex flex-col gap-6 max-w-6xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t('profile.title')}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t('profile.subtitle')}</p>
      </div>

      <Tabs defaultValue="personal">
        <TabsList>
          <TabsTrigger value="personal">{t('profile.tabs.personal')}</TabsTrigger>
          <TabsTrigger value="company">{t('profile.tabs.company')}</TabsTrigger>
          <TabsTrigger value="security">{t('profile.tabs.security')}</TabsTrigger>
        </TabsList>

        {/* Personal Data Tab */}
        <TabsContent value="personal">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('profile.personalInfo.title')}</CardTitle>
              <CardDescription>{t('profile.personalInfo.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <ImageUpload
                value={profile.avatarUrl}
                onUpload={handleAvatarUpload}
                onRemove={handleAvatarRemove}
                fallback={profile.avatarInitials}
                shape="circle"
                label={t('profile.personalInfo.avatar')}
                description={`${profile.firstName} ${profile.lastName} · ${profile.email}`}
              />

              <Separator />

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="lastName">{t('profile.fields.lastName')}</Label>
                  <Input id="lastName" value={form.lastName} onChange={(e) => setForm({ ...form, lastName: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="firstName">{t('profile.fields.firstName')}</Label>
                  <Input id="firstName" value={form.firstName} onChange={(e) => setForm({ ...form, firstName: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="email">{t('profile.fields.email')}</Label>
                  <Input id="email" type="email" value={form.email} disabled />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="phone">{t('profile.fields.phone')}</Label>
                  <Input id="phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="position">{t('profile.fields.position')}</Label>
                  <Input id="position" value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })} />
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Shield className="h-4 w-4" />
                  {t('profile.personalInfo.role')}: <Badge variant="outline">{t(roleLabels[role])}</Badge>
                </div>
              </div>

              <div className="flex justify-end">
                <Button onClick={handleSave} disabled={saving} className="gap-2">
                  <Save className="h-4 w-4" />
                  {saving ? t('common.saving') : t('profile.personalInfo.saveChanges')}
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Company Tab */}
        <TabsContent value="company">
          <CompanyTab />
        </TabsContent>

        {/* Security Tab — only password change is real; 2FA + active-sessions
            were UI placeholders and were removed until backend supports them. */}
        <TabsContent value="security">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('profile.security.title')}</CardTitle>
              <CardDescription>{t('profile.security.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between rounded-lg border p-4">
                <div className="flex items-center gap-3">
                  <KeyRound className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium">{t('profile.security.password')}</p>
                    <p className="text-xs text-muted-foreground">{t('profile.security.lastChanged')}</p>
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => setPasswordDialog(true)}>
                  {t('profile.security.change')}
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Password Dialog */}
      <Dialog open={passwordDialog} onOpenChange={setPasswordDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('profile.passwordDialog.title')}</DialogTitle>
            <DialogDescription>{t('profile.passwordDialog.description')}</DialogDescription>
          </DialogHeader>
          <PasswordChangeForm onClose={() => setPasswordDialog(false)} />
        </DialogContent>
      </Dialog>
    </div>
  );
}
