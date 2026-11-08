import { useId, useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { KeyRound, MailCheck, RotateCw, Send } from 'lucide-react';

import { loginErrorText } from '@/api/errors';
import { exchangeLoginCode, requestMagicLink, type Me } from '@/api/portal';
import { botLink, isPortalMock } from '@/app/links';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useNow } from '@/hooks/useNow';
import { ME_QUERY_KEY, afterSignIn } from '@/session/session';
import { codeDigits, secondsLeft } from './loginCode';
import { AuthLayout } from './AuthLayout';

type SentState = { email?: string; sentAt?: number } | null;

/**
 * «Если адрес зарегистрирован, мы отправили письмо» (`/login/sent`) и «Вход по коду» (`/login/code`), B-MAIL-1. Письмо может идти несколько минут, а
 * ссылка — открыться на другом устройстве, поэтому в письме и код из 6 цифр: клиент вводит его здесь (как Slack, Notion,
 * Stripe), `autocomplete="one-time-code"` подставляет код с телефона. «Отправить ещё раз» — через 60 секунд после письма
 * (сервер всё равно держит лимит 5 писем в час на адрес). Ответ `POST /auth/magic-link` один для любого адреса (FX-3), поэтому текст не
 * утверждает, что адрес есть. Код из приглашения вводится на `/login/code` без нового письма.
 */
export function LoginSentPage({ mode = 'sent' }: { mode?: 'sent' | 'code' }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const state = useLocation().state as SentState;
  const codeId = useId();
  const emailId = useId();
  const codeErrorId = useId();
  const resendErrorId = useId();
  const [email, setEmail] = useState(state?.email ?? '');
  const [code, setCode] = useState('');
  const [sentAt, setSentAt] = useState<number | null>(mode === 'sent' ? (state?.sentAt ?? null) : null);
  const [resent, setResent] = useState(false);
  const now = useNow(1000);
  const wait = sentAt === null ? 0 : secondsLeft(sentAt, now);
  const telegramLink = botLink();
  const emailQuery = state?.email ? `?email=${encodeURIComponent(state.email)}` : '';

  const signIn = useMutation({
    mutationFn: () => exchangeLoginCode(email.trim(), code),
    onSuccess: (me) => {
      queryClient.setQueryData<Me | null>(ME_QUERY_KEY, afterSignIn(me));
      navigate('/', { replace: true });
    },
  });
  const resend = useMutation({
    mutationFn: () => requestMagicLink(email.trim()),
    onSuccess: () => {
      setSentAt(Date.now());
      setResent(true);
      setCode('');
      signIn.reset();
    },
  });

  // Пришли на экран отправки без адреса (перезагрузка, закладка) — это вход по коду с полем адреса.
  if (mode === 'sent' && !state?.email) return <Navigate to="/login/code" replace />;

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    signIn.mutate();
  };
  const title = mode === 'sent' ? t('auth.sent.title') : t('auth.code.title');

  return (
    <AuthLayout title={title}>
      <Card>
        <CardHeader>
          {mode === 'sent' ? (
            <MailCheck className="size-8 text-primary" aria-hidden="true" />
          ) : (
            <KeyRound className="size-8 text-primary" aria-hidden="true" />
          )}
          <CardTitle>
            <h1 className="text-xl">{title}</h1>
          </CardTitle>
          <CardDescription className="break-words">
            {mode === 'sent' ? t('auth.sent.text', { email: state?.email }) : t('auth.code.text')}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form className="flex flex-col gap-3" onSubmit={onSubmit} aria-label={t('auth.code.form')}>
            {mode === 'code' ? (
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
                />
              </div>
            ) : null}
            <div className="flex flex-col gap-2">
              <Label htmlFor={codeId}>{t('auth.code.label')}</Label>
              <Input
                id={codeId}
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                placeholder="000000"
                className="text-center text-lg tracking-[0.4em] tabular-nums"
                value={code}
                onChange={(event) => setCode(codeDigits(event.target.value))}
                aria-invalid={signIn.isError || undefined}
                aria-describedby={signIn.isError ? codeErrorId : undefined}
              />
            </div>
            {signIn.isError ? (
              <Alert variant="destructive" id={codeErrorId}>
                <AlertDescription>{loginErrorText(signIn.error, t)}</AlertDescription>
              </Alert>
            ) : null}
            <Button type="submit" disabled={signIn.isPending || code.length !== 6}>
              {signIn.isPending ? t('auth.code.signingIn') : t('auth.code.submit')}
            </Button>
          </form>

          <p className="text-sm text-muted-foreground">{t('auth.sent.hint')}</p>

          <div className="flex flex-col gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={wait > 0 || resend.isPending || !email.trim()}
              aria-describedby={resend.isError ? resendErrorId : undefined}
              onClick={() => resend.mutate()}
            >
              <RotateCw aria-hidden="true" />
              {wait > 0 ? t('auth.sent.resendIn', { seconds: wait }) : t('auth.sent.resend')}
            </Button>
            <p className="min-h-5 text-center text-xs text-muted-foreground" role="status">
              {resent && !resend.isError ? t('auth.sent.resent') : ''}
            </p>
            {resend.isError ? (
              <Alert variant="destructive" id={resendErrorId}>
                <AlertDescription>{loginErrorText(resend.error, t)}</AlertDescription>
              </Alert>
            ) : null}
          </div>

          {telegramLink ? (
            <Button asChild variant="outline">
              <a href={telegramLink} target="_blank" rel="noopener noreferrer">
                <Send aria-hidden="true" />
                {t('auth.login.telegram')}
              </a>
            </Button>
          ) : null}
          {isPortalMock() ? (
            <Button asChild variant="secondary">
              <Link
                to={{ pathname: '/auth/magic', hash: '#token=demo-token-mock-link' }}
                onClick={() => {
                  sessionStorage.setItem(
                    'cabinet.mock.session',
                    JSON.stringify({ role: 'actor', auth_method: 'magic_link', dataset: 'demo' }),
                  );
                }}
              >
                {t('auth.sent.mockLink')}
              </Link>
            </Button>
          ) : null}
          <Button asChild variant="ghost">
            <Link to="/login">{t('auth.sent.back')}</Link>
          </Button>
          <Link
            to={`/new-client${emailQuery}`}
            className="text-center text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            {t('auth.sent.newClientLink')}
          </Link>
          <Link
            to={`/become-partner${emailQuery}`}
            className="text-center text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            {t('auth.login.becomePartner')}
          </Link>
        </CardContent>
      </Card>
    </AuthLayout>
  );
}
