import { useId, useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Eye, Mail, Send, Sparkles, UserCheck, UserPlus } from 'lucide-react';

import { loginErrorText } from '@/api/errors';
import { requestMagicLink } from '@/api/portal';
import { botLink, isPortalMock } from '@/app/links';
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
  const telegramHintId = useId();
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
      {isPortalMock() ? (
        <Card className="border-navy/20 bg-ice-navy/40 shadow-sm">
          <CardHeader>
            <div className="flex items-center gap-2">
              <Sparkles className="size-5 text-navy" aria-hidden="true" />
              <CardTitle>
                <span className="text-base font-semibold text-navy">
                  {t('auth.login.demoTitle')}
                </span>
              </CardTitle>
            </div>
            <CardDescription>{t('auth.login.demoHint')}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2.5">
            <Button
              type="button"
              className="w-full justify-start bg-navy text-primary-foreground hover:bg-navy/90"
              onClick={() => {
                sessionStorage.setItem(
                  'cabinet.mock.session',
                  JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo' }),
                );
                window.location.href = '/requests';
              }}
            >
              <UserCheck className="size-4 mr-2" aria-hidden="true" />
              {t('auth.login.demoActor')}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="w-full justify-start bg-white hover:bg-muted/50 text-foreground"
              onClick={() => {
                sessionStorage.setItem(
                  'cabinet.mock.session',
                  JSON.stringify({ role: 'viewer', auth_method: 'magic_link', dataset: 'demo' }),
                );
                window.location.href = '/requests';
              }}
            >
              <Eye className="size-4 mr-2 text-muted-foreground" aria-hidden="true" />
              {t('auth.login.demoViewer')}
            </Button>
          </CardContent>
        </Card>
      ) : null}
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
                <AlertDescription>{loginErrorText(magicLink.error, t)}</AlertDescription>
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
                <a
                  href={telegramLink}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-describedby={telegramHintId}
                >
                  <Send aria-hidden="true" />
                  {t('auth.login.telegram')}
                </a>
              </Button>
              <p id={telegramHintId} className="text-center text-xs text-muted-foreground">
                {t('auth.login.telegramHint')}
              </p>
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
