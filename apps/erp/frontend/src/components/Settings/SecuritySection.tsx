/**
 * Секция «Безопасность» Settings Hub — карточный layout (spec §3 PR 2):
 * двухколоночный паттерн §2.4 (слева заголовок+описание секции), справа карточки
 * пароля и 2FA с капом ширины; список активных сессий — full width
 * (memory-стандарт ширины: данные/таблицы заполняют viewport).
 * Смена пароля и 2FA-флоу (setup→verify→disable) функционально не менялись.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { KeyRound } from 'lucide-react';
import { toast } from 'sonner';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';

import { accountsApi } from '@/api/accountsApi';
import { translateApiError } from '@/lib/apiError';
import { TwoFactorAuth } from '@/components/Cabinet/TwoFactorAuth';
import { ActiveSessions } from '@/components/Cabinet/ActiveSessions';

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
          <Label htmlFor="current-password">{t('profile.passwordDialog.currentPassword')}</Label>
          <Input
            id="current-password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="new-password">{t('profile.passwordDialog.newPassword')}</Label>
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="confirm-password">{t('profile.passwordDialog.confirmPassword')}</Label>
          <Input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
          />
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

export function SecuritySection() {
  const { t } = useTranslation();
  const [passwordDialog, setPasswordDialog] = useState(false);

  return (
    <div className="space-y-6">
      <div className="grid gap-6 md:grid-cols-[240px_1fr]">
        {/* Левая колонка — заголовок и описание секции (§2.4) */}
        <div className="space-y-1">
          <h3 className="text-base font-semibold">{t('settings.security.sectionTitle')}</h3>
          <p className="text-sm text-muted-foreground">{t('settings.security.sectionDescription')}</p>
        </div>

        {/* Правая колонка — карточки пароля и 2FA (кап ширины reading-форм) */}
        <div className="min-w-0 max-w-2xl space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <KeyRound className="h-5 w-5 text-muted-foreground" />
                <CardTitle className="text-base">{t('profile.security.password')}</CardTitle>
              </div>
              <CardDescription>{t('settings.security.passwordDescription')}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" size="sm" onClick={() => setPasswordDialog(true)}>
                {t('profile.security.change')}
              </Button>
            </CardContent>
          </Card>

          <TwoFactorAuth />
        </div>
      </div>

      {/* Активные сессии — данные, full width (§2.4: без капа ширины) */}
      <ActiveSessions />

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
