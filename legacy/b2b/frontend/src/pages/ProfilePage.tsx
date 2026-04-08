import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Shield, Save, Camera, KeyRound, Globe,
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';

import { useUserStore, roleLabels, companyStatusLabels } from '@/store/userStore';
import { accountsApi } from '@/api/accountsApi';
import { toast } from 'sonner';

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
    } catch {
      toast.error(t('profile.passwordDialog.error'));
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

export function ProfilePage() {
  const { t } = useTranslation();
  const { profile, company, role, activeStatus, updateProfile } = useUserStore();
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
      });
      updateProfile(form);
      toast.success(t('profile.personalInfo.saved'));
    } catch {
      toast.error(t('profile.personalInfo.saveError'));
    } finally {
      setSaving(false);
    }
  };

  const kycBadge = {
    verified: { label: t('profile.kyc.verified'), variant: 'secondary' as const, className: 'bg-success/10 text-success border-success/20' },
    pending: { label: t('profile.kyc.pending'), variant: 'secondary' as const, className: 'bg-warning/10 text-warning border-warning/20' },
    not_started: { label: t('profile.kyc.notStarted'), variant: 'destructive' as const, className: '' },
  }[company.kycStatus];

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t('profile.title')}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t('profile.subtitle')}</p>
      </div>

      <Tabs defaultValue="personal">
        <TabsList>
          <TabsTrigger value="personal">{t('profile.tabs.personal')}</TabsTrigger>
          <TabsTrigger value="company">{t('profile.tabs.company')}</TabsTrigger>
          <TabsTrigger value="security">{t('profile.tabs.security')}</TabsTrigger>
          <TabsTrigger value="notifications">{t('profile.tabs.notifications')}</TabsTrigger>
        </TabsList>

        {/* Personal Data Tab */}
        <TabsContent value="personal">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('profile.personalInfo.title')}</CardTitle>
              <CardDescription>{t('profile.personalInfo.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Avatar */}
              <div className="flex items-center gap-4">
                <Avatar className="h-20 w-20">
                  <AvatarFallback className="bg-primary text-primary-foreground text-lg">
                    {profile.avatarInitials}
                  </AvatarFallback>
                </Avatar>
                <div>
                  <Button variant="outline" size="sm" className="gap-2" disabled>
                    <Camera className="h-4 w-4" />
                    {t('profile.personalInfo.uploadPhoto')}
                  </Button>
                  <p className="text-xs text-muted-foreground mt-1">{t('profile.personalInfo.photoHint')}</p>
                </div>
              </div>

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
                  <Label htmlFor="patronymic">{t('profile.fields.patronymic')}</Label>
                  <Input id="patronymic" value={form.patronymic} onChange={(e) => setForm({ ...form, patronymic: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="position">{t('profile.fields.position')}</Label>
                  <Input id="position" value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="email">{t('profile.fields.email')}</Label>
                  <Input id="email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="phone">{t('profile.fields.phone')}</Label>
                  <Input id="phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
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
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('profile.companyInfo.title')}</CardTitle>
              <CardDescription>{t('profile.companyInfo.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>{t('profile.companyInfo.name')}</Label>
                  <Input value={company.name} disabled />
                </div>
                <div className="space-y-2">
                  <Label>{t('profile.companyInfo.inn')}</Label>
                  <Input value={company.inn} disabled />
                </div>
                <div className="space-y-2">
                  <Label>{t('profile.companyInfo.country')}</Label>
                  <Input value={company.country} disabled />
                </div>
                <div className="space-y-2">
                  <Label>{t('profile.companyInfo.city')}</Label>
                  <Input value={company.city} disabled />
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
              <p className="text-xs text-muted-foreground">
                {t('profile.companyInfo.contactAdmin')}
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Security Tab */}
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

              <div className="flex items-center justify-between rounded-lg border p-4">
                <div className="flex items-center gap-3">
                  <Shield className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium">{t('profile.security.twoFactor')}</p>
                    <p className="text-xs text-muted-foreground">{t('profile.security.twoFactorDesc')}</p>
                  </div>
                </div>
                <Switch />
              </div>

              <div className="flex items-center justify-between rounded-lg border p-4">
                <div className="flex items-center gap-3">
                  <Globe className="h-5 w-5 text-muted-foreground" />
                  <div>
                    <p className="text-sm font-medium">{t('profile.security.activeSessions')}</p>
                    <p className="text-xs text-muted-foreground">{t('profile.security.activeDevices')}</p>
                  </div>
                </div>
                <Button variant="outline" size="sm" disabled>{t('profile.security.manage')}</Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Notifications Tab */}
        <TabsContent value="notifications">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('profile.notifications.title')}</CardTitle>
              <CardDescription>{t('profile.notifications.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {[
                { titleKey: 'profile.notifications.newDeals', descKey: 'profile.notifications.newDealsDesc', defaultOn: true },
                { titleKey: 'profile.notifications.requestStatus', descKey: 'profile.notifications.requestStatusDesc', defaultOn: true },
                { titleKey: 'profile.notifications.chatMessages', descKey: 'profile.notifications.chatMessagesDesc', defaultOn: true },
                { titleKey: 'profile.notifications.excelImport', descKey: 'profile.notifications.excelImportDesc', defaultOn: true },
                { titleKey: 'profile.notifications.system', descKey: 'profile.notifications.systemDesc', defaultOn: false },
                { titleKey: 'profile.notifications.emailDigest', descKey: 'profile.notifications.emailDigestDesc', defaultOn: false },
              ].map((item) => (
                <div key={item.titleKey} className="flex items-center justify-between rounded-lg border p-4">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{t(item.titleKey)}</p>
                    <p className="text-xs text-muted-foreground">{t(item.descKey)}</p>
                  </div>
                  <Switch defaultChecked={item.defaultOn} />
                </div>
              ))}
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
