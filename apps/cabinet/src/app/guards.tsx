import { useEffect, useState } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { apiErrorKey, loginErrorText } from '@/api/errors';
import { isPortalApiError } from '@/api/portal';
import { useCompanyPartnerApplication } from '@/api/queries';
import { PartnerApplicationCard } from '@/pages/company';
import { botLink } from './links';
import { StatusScreen } from '@/components/StatusScreen';
import { Button } from '@/components/ui/button';
import { useAppMode } from '@/session/mode';
import { useMe } from '@/session/useMe';
import { clearReturnTo, readReturnTo, rememberReturnTo } from '@/session/returnTo';
import { useNav } from '@/session/useNav';
import { navItemFor } from './nav';
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
  const signedOut = mode === 'web' && !session.isPending && !session.isError && !session.data;
  const here = `${location.pathname}${location.search}${location.hash}`;
  // Без сессии — запомнить адрес (ссылка из письма), после входа `HomeRedirect` вернёт сюда.
  useEffect(() => {
    if (signedOut) rememberReturnTo(here);
  }, [signedOut, here]);

  if (session.isPending) {
    return <StatusScreen title={mode === 'miniapp' ? t('auth.telegram.signingIn') : t('app.loading')} loading />;
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
    <StatusScreen
      title={t('auth.telegram.failedTitle')}
      text={`${isPortalApiError(error, 403) ? loginErrorText(error, t) : t(apiErrorKey(error))} ${t('auth.telegram.failedText')}`}
    >
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

/**
 * Корень `/` → адрес, с которого отправили на вход (ссылка из письма, `session/returnTo.ts`), иначе первый раздел сессии
 * (у клиента «Запросы»; deep-link Mini App разрешается раньше — `initialPath`).
 */
export function HomeRedirect() {
  const { work } = useNav();
  // Кандидат в партнёры (`invited`, модули — только обязательные): его рабочее место — заявка и договор (FX-1)
  const onlyChat = work.length > 0 && work.every((item) => item.module === 'messages');
  const application = useCompanyPartnerApplication({ enabled: onlyChat });
  // Адрес, с которого отправили на вход (`RequireSession`), — один раз; потом обычный первый раздел.
  const [back] = useState(() => readReturnTo());
  useEffect(() => {
    if (back) clearReturnTo();
  }, [back]);
  if (back) return <Navigate to={back} replace />;
  if (onlyChat && application.isPending) return null;
  if (onlyChat && application.data?.has_application) {
    return (
      <div className="mx-auto max-w-2xl py-8">
        <PartnerApplicationCard />
      </div>
    );
  }
  // Нет рабочих разделов — остаёмся на «/»: оболочка показывает «Доступ открыт» и «Профиль» в меню
  if (work.length === 0) return null;
  return <Navigate to={work[0]?.to ?? '/requests'} replace />;
}

/**
 * Раздел вне модулей сессии (ADR-0022) — не страница с ошибкой 403, а возврат в первый доступный раздел.
 * Адреса вне меню (`/deals/…`, `/requests/new` — внутри «Запросов») проходят по модулю своего раздела; незнакомые — на 404.
 */
export function RequireModule() {
  const { pathname } = useLocation();
  const { items, work } = useNav();
  const section = navItemFor(pathname);
  if (section && !items.some((item) => item.module === section.module)) {
    // «Компания» кандидата ведёт на главную — там его заявка (FX-1); без заявки главная отправит в первый раздел
    return <Navigate to={section.module === 'company' ? '/' : (work[0]?.to ?? '/')} replace />;
  }
  return <Outlet />;
}
