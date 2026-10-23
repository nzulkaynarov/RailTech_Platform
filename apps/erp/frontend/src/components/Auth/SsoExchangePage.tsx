import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Train, Loader2, AlertCircle } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { exchangeSsoToken } from '@/api/ssoApi';
import { setAccessToken } from '@/api/accessToken';
import { useAuthStore } from '@/store/authStore';
import { queryClient } from '@/lib/queryClient';

// Токен CRM одноразовый (jti). StrictMode (dev) монтирует эффект дважды — второй обмен того же токена
// получил бы TOKEN_ALREADY_USED, поэтому обмен один на токен, а оба монтирования ждут его результат.
const pendingExchanges = new Map<string, ReturnType<typeof exchangeSsoToken>>();

function exchangeOnce(token: string) {
  let p = pendingExchanges.get(token);
  if (!p) {
    p = exchangeSsoToken(token);
    pendingExchanges.set(token, p);
  }
  return p;
}

export const SsoExchangePage: React.FC = () => {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function processToken() {
      // Извлекаем токен из фрагмента URL: #token=<jwt> (ADR-0003, docs/architecture/sso-token.md)
      const hash = window.location.hash.replace(/^#/, '');
      const searchParams = new URLSearchParams(hash);
      const token = searchParams.get('token') || (hash.startsWith('token=') ? hash.slice(6) : null);

      if (!token) {
        if (active) {
          setError(t('sso.missingToken'));
          setLoading(false);
        }
        return;
      }

      try {
        const data = await exchangeOnce(token);
        if (!active) return;

        setAccessToken(data.access_token);
        queryClient.clear();

        // Очищаем токен из адресной строки, чтобы он не оставался в истории браузера
        window.history.replaceState(null, '', '/');

        // Инициализируем профиль пользователя
        await useAuthStore.getState().initAuth();

        // Переходим на главную
        window.location.replace('/');
      } catch (err) {
        if (!active) return;
        const msg = err instanceof Error ? err.message : 'SSO_EXCHANGE_FAILED';
        if (msg === 'USER_INACTIVE') {
          setError(t('sso.userInactive'));
        } else if (msg === 'TOKEN_ALREADY_USED') {
          setError(t('sso.tokenAlreadyUsed'));
        } else {
          setError(t('sso.exchangeFailed'));
        }
        setLoading(false);
      }
    }

    processToken();

    return () => {
      active = false;
    };
  }, [t]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-md shadow-lg border-muted">
        <CardHeader className="text-center space-y-2">
          <div className="mx-auto w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
            <Train className="w-6 h-6" />
          </div>
          <CardTitle className="text-xl font-bold">
            {t('sso.title')}
          </CardTitle>
          <CardDescription>
            {loading
              ? t('sso.processing')
              : t('sso.complete')}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading && (
            <div className="flex flex-col items-center justify-center py-6 space-y-3">
              <Loader2 className="w-8 h-8 animate-spin text-primary" />
              <p className="text-sm text-muted-foreground">
                {t('sso.authenticating')}
              </p>
            </div>
          )}

          {error && (
            <div className="space-y-4">
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
              <Button
                className="w-full"
                onClick={() => {
                  window.location.replace('/');
                }}
              >
                {t('sso.goToLogin')}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
