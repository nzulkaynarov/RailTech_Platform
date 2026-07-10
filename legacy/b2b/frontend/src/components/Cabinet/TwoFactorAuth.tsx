import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ShieldCheck, ShieldAlert } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { accountsApi } from '@/api/accountsApi';
import { getErrorMessage } from '@/api/client';
import { useUserStore } from '@/store/userStore';

// Backend answers with error CODES ({"detail": "2FA_INVALID_CODE"}) — map to i18n.
const ERROR_KEYS: Record<string, string> = {
  '2FA_INVALID_CODE': 'profile.security.invalidCode',
  '2FA_CODE_REQUIRED': 'profile.security.codeRequired',
  '2FA_ALREADY_ENABLED': 'profile.security.alreadyEnabled',
};

export function TwoFactorAuth() {
  const { t } = useTranslation();
  const { profile, updateProfile } = useUserStore();
  const [setupData, setSetupData] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);

  const is2faEnabled = profile.is_2fa_enabled;

  const toastApiError = (error: unknown, fallbackKey: string) => {
    const detail = getErrorMessage(error);
    toast.error(t(ERROR_KEYS[detail] ?? fallbackKey));
  };

  const handleSetup = async () => {
    try {
      setLoading(true);
      const data = await accountsApi.setup2FA();
      setSetupData(data);
    } catch (error) {
      toastApiError(error, 'common.error');
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async () => {
    if (!setupData || !code) return;
    try {
      setLoading(true);
      await accountsApi.verify2FA({ secret: setupData.secret, code });
      toast.success(t('profile.security.twoFactorEnabled'));
      updateProfile({ is_2fa_enabled: true });
      setSetupData(null);
      setCode('');
    } catch (error) {
      toastApiError(error, 'profile.security.invalidCode');
    } finally {
      setLoading(false);
    }
  };

  const handleDisable = async () => {
    if (!code) {
      toast.error(t('profile.security.codeRequired'));
      return;
    }
    try {
      setLoading(true);
      await accountsApi.disable2FA({ code });
      toast.success(t('profile.security.twoFactorDisabled'));
      updateProfile({ is_2fa_enabled: false });
      setCode('');
    } catch (error) {
      toastApiError(error, 'profile.security.invalidCode');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          {is2faEnabled ? <ShieldCheck className="h-5 w-5 text-success" /> : <ShieldAlert className="h-5 w-5 text-warning" />}
          <CardTitle className="text-base">{t('profile.security.twoFactor')}</CardTitle>
        </div>
        <CardDescription>{t('profile.security.twoFactorDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {is2faEnabled ? (
          <div className="space-y-4">
            <p className="text-sm">{t('profile.security.twoFactorActive')}</p>
            <div className="flex flex-col gap-2 max-w-sm">
              <Label>{t('profile.security.enterCodeToDisable')}</Label>
              <div className="flex gap-2">
                <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="000000" maxLength={6} />
                <Button variant="destructive" onClick={handleDisable} disabled={loading || code.length !== 6}>
                  {t('common.disable')}
                </Button>
              </div>
            </div>
          </div>
        ) : setupData ? (
          <div className="space-y-4">
            {/* Authenticator scanners need a light quiet zone even in dark mode —
                marginSize renders it INSIDE the SVG instead of a hardcoded bg. */}
            <div className="inline-block overflow-hidden rounded-lg border">
              <QRCodeSVG value={setupData.uri} size={200} marginSize={3} />
            </div>
            <div className="space-y-2 max-w-sm">
              <Label>{t('profile.security.enterCode')}</Label>
              <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="000000" maxLength={6} />
              <div className="flex gap-2">
                <Button onClick={handleVerify} disabled={loading || code.length !== 6}>
                  {t('common.verify')}
                </Button>
                <Button variant="outline" onClick={() => setSetupData(null)}>
                  {t('common.cancel')}
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <Button onClick={handleSetup} disabled={loading}>
            {t('profile.security.enableTwoFactor')}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
