/**
 * Секция «Личные данные» Settings Hub — контент перенесён из ProfilePage (таб personal)
 * как есть (spec PR 1): персональные данные + аватар + язык/тема. Редизайн — PR 2.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Shield, Save } from 'lucide-react';
import { toast } from 'sonner';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

import { useUserStore, roleLabels } from '@/store/userStore';
import { useThemeStore } from '@/store/themeStore';
import { accountsApi } from '@/api/accountsApi';
import { ImageUpload } from '@/components/Shared/ImageUpload';

export function ProfileSection() {
  const { t, i18n } = useTranslation();
  const { theme, setTheme } = useThemeStore();
  const { profile, role, updateProfile } = useUserStore();
  const [form, setForm] = useState({
    ...profile,
    language: i18n.language?.startsWith('ru') ? 'ru' : 'en',
    theme: theme,
  });
  const [saving, setSaving] = useState(false);

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
  );
}
