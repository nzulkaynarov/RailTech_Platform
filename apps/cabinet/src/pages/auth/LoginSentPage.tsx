import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { MailCheck } from 'lucide-react';

import { isPortalMock } from '@/app/links';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { AuthLayout } from './AuthLayout';

/**
 * «Проверьте почту»: ответ `POST /auth/magic-link` всегда 200, поэтому текст не утверждает, что адрес есть
 * («Если адрес зарегистрирован, мы отправили ссылку»), а новому клиенту сразу показан путь — оставить запрос.
 */
export function LoginSentPage() {
  const { t } = useTranslation();
  const email = (useLocation().state as { email?: string } | null)?.email;

  return (
    <AuthLayout title={t('auth.sent.title')}>
      <Card>
        <CardHeader>
          <MailCheck className="size-8 text-primary" aria-hidden="true" />
          <CardTitle>
            <h1 className="text-xl">{t('auth.sent.title')}</h1>
          </CardTitle>
          <CardDescription className="break-words" aria-live="polite">
            {email ? t('auth.sent.text', { email }) : t('auth.sent.textNoEmail')}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">{t('auth.sent.noLetter')}</p>
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
          <Button asChild variant="outline">
            <Link to="/login">{t('auth.sent.back')}</Link>
          </Button>
          <Link
            to="/new-client"
            className="text-center text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            {t('auth.sent.newClientLink')}
          </Link>
        </CardContent>
      </Card>
    </AuthLayout>
  );
}
