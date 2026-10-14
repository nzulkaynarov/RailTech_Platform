import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Send, UserPlus } from 'lucide-react';

import { botLink } from '@/app/links';
import { EmptyState } from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { AuthLayout } from './AuthLayout';

/**
 * «Я новый клиент» (ARCHITECTURE §17): форма «Запрос» → лид CRM с источником `web`
 * (`POST /api/v1/leads/web`, `consent: true` — DECISIONS Q-12) появится в M2-CAB-03.
 * Пока — заглушка формы и «Написать в Telegram» с меткой `start=web`.
 */
export function NewClientPage() {
  const { t } = useTranslation();
  const telegramLink = botLink('web');

  return (
    <AuthLayout title={t('newClient.title')}>
      <h1 className="text-xl font-semibold">{t('newClient.title')}</h1>
      <EmptyState icon={UserPlus} title={t('newClient.formTitle')} text={t('newClient.text')}>
        {telegramLink ? (
          <Button asChild>
            <a href={telegramLink} target="_blank" rel="noopener noreferrer">
              <Send aria-hidden="true" />
              {t('newClient.writeTelegram')}
            </a>
          </Button>
        ) : null}
      </EmptyState>
      <Button asChild variant="link" className="self-center">
        <Link to="/login">{t('newClient.backToLogin')}</Link>
      </Button>
    </AuthLayout>
  );
}
