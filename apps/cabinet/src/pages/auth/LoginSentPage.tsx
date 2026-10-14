import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { MailCheck } from 'lucide-react';

import { isPortalMock } from '@/app/links';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { AuthLayout } from './AuthLayout';

/** «Письмо отправлено»: ответ `POST /auth/magic-link` всегда 200, поэтому текст не утверждает, что адрес есть. */
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
        <CardContent className="flex flex-col gap-2">
          {isPortalMock() ? (
            <Button asChild variant="secondary">
              <Link to="/auth/magic/demo">{t('auth.sent.mockLink')}</Link>
            </Button>
          ) : null}
          <Button asChild variant="outline">
            <Link to="/login">{t('auth.sent.back')}</Link>
          </Button>
        </CardContent>
      </Card>
    </AuthLayout>
  );
}
