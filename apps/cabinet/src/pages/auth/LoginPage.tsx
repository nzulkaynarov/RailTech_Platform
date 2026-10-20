import { useId, useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Mail, Send, UserPlus } from 'lucide-react';

import { loginErrorKey } from '@/api/errors';
import { requestMagicLink } from '@/api/portal';
import { botLink } from '@/app/links';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useMe } from '@/session/useMe';
import { AuthLayout } from './AuthLayout';

/**
 * Вход с веба (ARCHITECTURE §17): два пути — «Войти» (magic-link на e-mail; Telegram — через бота)
 * и «Я новый клиент» (форма запроса → лид CRM `web`, M2-CAB-03). Регистрации нет: вход по приглашению.
 */
export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const emailId = useId();
  const errorId = useId();
  const [email, setEmail] = useState('');
  const me = useMe().data;
  const telegramLink = botLink();

  const magicLink = useMutation({
    mutationFn: (address: string) => requestMagicLink(address),
    onSuccess: (_data, address) => navigate('/login/sent', { state: { email: address } }),
  });

  if (me) return <Navigate to="/" replace />;

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    magicLink.mutate(email.trim());
  };

  return (
    <AuthLayout title={t('auth.login.title')}>
      <Card>
        <CardHeader>
          <CardTitle>
            <h1 className="text-xl">{t('auth.login.title')}</h1>
          </CardTitle>
          <CardDescription>{t('auth.login.subtitle')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form className="flex flex-col gap-3" onSubmit={onSubmit}>
            <div className="flex flex-col gap-2">
              <Label htmlFor={emailId}>{t('auth.login.email')}</Label>
              <Input
                id={emailId}
                type="email"
                inputMode="email"
                autoComplete="email"
                required
                placeholder={t('auth.login.emailPlaceholder')}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                aria-invalid={magicLink.isError || undefined}
                aria-describedby={magicLink.isError ? errorId : undefined}
              />
            </div>
            {magicLink.isError ? (
              <Alert variant="destructive" id={errorId}>
                <AlertDescription>{t(loginErrorKey(magicLink.error))}</AlertDescription>
              </Alert>
            ) : null}
            <Button type="submit" disabled={magicLink.isPending}>
              <Mail aria-hidden="true" />
              {magicLink.isPending ? t('auth.login.sending') : t('auth.login.submit')}
            </Button>
          </form>
          {telegramLink ? (
            <>
              <p className="text-center text-xs text-muted-foreground">{t('auth.login.or')}</p>
              <Button asChild variant="outline">
                <a href={telegramLink} target="_blank" rel="noopener noreferrer">
                  <Send aria-hidden="true" />
                  {t('auth.login.telegram')}
                </a>
              </Button>
            </>
          ) : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>
            <h2 className="text-base">{t('auth.login.newClient')}</h2>
          </CardTitle>
          <CardDescription>{t('auth.login.newClientHint')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild variant="secondary" className="w-full">
            <Link to="/new-client">
              <UserPlus aria-hidden="true" />
              {t('auth.login.newClient')}
            </Link>
          </Button>
        </CardContent>
      </Card>
    </AuthLayout>
  );
}
