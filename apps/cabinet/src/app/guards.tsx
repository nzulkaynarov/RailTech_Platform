import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { apiErrorKey, loginErrorText } from '@/api/errors';
import { isPortalApiError } from '@/api/portal';
import { botLink } from './links';
import { StatusScreen } from '@/components/StatusScreen';
import { Button } from '@/components/ui/button';
import { useAppMode } from '@/session/mode';
import { useMe } from '@/session/useMe';
import { getTelegramWebApp } from '@/telegram/webapp';

/**
 * Доступ к кабинету только с сессией портала. Веб без сессии → `/login`; Mini App входит сам
 * (`POST /auth/telegram`), страницы входа там нет — при отказе экран «откройте из бота ещё раз».
 */
export function RequireSession() {
  const { t } = useTranslation();
  const mode = useAppMode();
  const location = useLocation();
  const session = useMe();

  if (session.isPending) {
    return (
      <StatusScreen title={mode === 'miniapp' ? t('auth.telegram.signingIn') : t('app.loading')} loading />
    );
  }
  if (mode === 'miniapp' && !session.data) {
    return <TelegramSignInFailed error={session.error} onRetry={() => void session.refetch()} />;
  }
  if (session.isError) {
    return (
      <StatusScreen title={t('common.error')} text={t(apiErrorKey(session.error))}>
        <Button onClick={() => void session.refetch()}>{t('common.retry')}</Button>
      </StatusScreen>
    );
  }
  if (!session.data) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

function TelegramSignInFailed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useTranslation();
  const bot = botLink();
  const openBot = () => {
    const webApp = getTelegramWebApp();
    if (bot && webApp?.openTelegramLink) webApp.openTelegramLink(bot);
    else if (bot) window.open(bot, '_blank', 'noopener');
  };
  return (
    <StatusScreen title={t('auth.telegram.failedTitle')} text={`${isPortalApiError(error, 403) ? loginErrorText(error, t) : t(apiErrorKey(error))} ${t('auth.telegram.failedText')}`}>
      <Button onClick={onRetry}>{t('auth.telegram.retry')}</Button>
      {bot ? (
        <Button variant="outline" onClick={openBot}>
          {t('auth.telegram.openBot')}
        </Button>
      ) : null}
    </StatusScreen>
  );
}

/** Публичные экраны веба: в Mini App их нет — сразу в кабинет. */
export function WebOnly() {
  return useAppMode() === 'miniapp' ? <Navigate to="/" replace /> : <Outlet />;
}

/** Корень `/` → «Запросы» (deep-link Mini App разрешается раньше — `initialPath`). */
export function HomeRedirect() {
  return <Navigate to="/requests" replace />;
}
