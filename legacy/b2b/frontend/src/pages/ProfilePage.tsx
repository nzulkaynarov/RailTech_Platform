import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Shield, Save, KeyRound } from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';

import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';

import { useUserStore, roleLabels } from '@/store/userStore';
import { useThemeStore } from '@/store/themeStore';
import { accountsApi } from '@/api/accountsApi';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { ImageUpload } from '@/components/Shared/ImageUpload';
import { TwoFactorAuth } from '@/components/Cabinet/TwoFactorAuth';
import { ActiveSessions } from '@/components/Cabinet/ActiveSessions';

import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

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

export function ProfilePage() {
  const { t, i18n } = useTranslation();
  const { theme, setTheme } = useThemeStore();
  const { profile, role, updateProfile } = useUserStore();
  const [form, setForm] = useState({
    ...profile,
    language: i18n.language?.startsWith('ru') ? 'ru' : 'en',
    theme: theme,
  });
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
        preferences: {
          language: form.language,
          theme: form.theme,
        },
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
                  <p className="text-xs text-muted-foreground">
                    {t('profile.fields.emailDisabledHint')}
                  </p>
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

              <Separator />

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label>{t('settings.general.language')}</Label>
                  <Select value={form.language} onValueChange={(val) => {
                    setForm({ ...form, language: val });
                    i18n.changeLanguage(val);
                  }}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ru">{t('settings.general.langRu')}</SelectItem>
                      <SelectItem value="en">{t('settings.general.langEn')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>{t('settings.appearance.theme')}</Label>
                  <Select value={form.theme} onValueChange={(val) => {
                    setForm({ ...form, theme: val as 'light' | 'dark' });
                    setTheme(val as 'light' | 'dark');
                  }}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="light">{t('settings.appearance.themeLight')}</SelectItem>
                      <SelectItem value="dark">{t('settings.appearance.themeDark')}</SelectItem>
                    </SelectContent>
                  </Select>
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



        {/* Security Tab */}
        <TabsContent value="security" className="space-y-6">
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
          
          <TwoFactorAuth />
          <ActiveSessions />
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
