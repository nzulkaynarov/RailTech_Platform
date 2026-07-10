/**
 * Секция «Безопасность» Settings Hub — контент перенесён из ProfilePage (таб security)
 * как есть (spec PR 1): смена пароля (Dialog) + 2FA + активные сессии. Редизайн — PR 2.
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

export function SecuritySection() {
  const { t } = useTranslation();
  const [passwordDialog, setPasswordDialog] = useState(false);

  return (
    <div className="space-y-6">
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
