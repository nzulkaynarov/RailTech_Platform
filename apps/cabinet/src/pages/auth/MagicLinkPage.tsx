import { useEffect, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { loginErrorText } from '@/api/errors';
import { exchangeMagicToken, isPortalApiError, type Me } from '@/api/portal';
import { StatusScreen } from '@/components/StatusScreen';
import { Button } from '@/components/ui/button';
import { clearPendingMagicToken, consumePendingMagicToken, scrubTelegramToken, tokenFromHash } from '@/session/magicToken';
import { ME_QUERY_KEY, afterSignIn } from '@/session/session';
import { useMe } from '@/session/useMe';

/**
 * `/auth/magic#token=…` — ссылка из письма: токен берётся из фрагмента и уходит в теле
 * `POST /auth/magic {token}` → сессия → кабинет. Токен одноразовый, поэтому обмен — запрос React Query
 * с бесконечным сроком (повторный рендер или StrictMode не отправят его второй раз), а фрагмент сразу
 * убирается из адресной строки. 410 — «ссылка не действует» (если сеанс уже жив — «Вы уже вошли» с путём «В кабинет»),
 * 403 — «доступ закрыт», 429 — «слишком много попыток» (с `Retry-After`), сбой сети или 5xx — «Повторить»
 * с тем же токеном из памяти страницы: просить новую ссылку из-за обрыва связи не нужно.
 */
export function MagicLinkPage() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // Токен читается один раз и до любого запроса снимается с копий SDK Telegram; дальше фрагмент убирается
  // из адреса, а обмен остаётся привязан к этому значению. Обычно фрагмент уже забрал скрипт index.html.
  const [token] = useState(() => {
    const value = tokenFromHash(location.hash) || consumePendingMagicToken();
    scrubTelegramToken();
    return value;
  });

  useEffect(() => {
    if (location.hash) navigate({ pathname: location.pathname, search: location.search, hash: '' }, { replace: true });
  }, [location.hash, location.pathname, location.search, navigate]);

  useEffect(() => clearPendingMagicToken, []);

  const exchange = useQuery({
    queryKey: ['magic-link', token],
    queryFn: async () => {
      const me = afterSignIn(await exchangeMagicToken(token));
      queryClient.setQueryData<Me | null>(ME_QUERY_KEY, me);
      return me;
    },
    enabled: token !== '',
    retry: false,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
  });

  // Для 410/422 (и пустого токена) смотрим, не жив ли уже сеанс: повторное открытие ссылки не должно быть тупиком.
  const failure = exchange.isError ? exchange.error : null;
  const spent = token === '' || isPortalApiError(failure, 410) || isPortalApiError(failure, 422);
  const session = useMe({ enabled: spent && !exchange.isFetching });

  if (exchange.isSuccess) return <Navigate to="/" replace />;
  if (exchange.isFetching) return <StatusScreen title={t('auth.magic.exchanging')} loading />;
  if (spent) {
    if (session.isPending) return <StatusScreen title={t('auth.magic.exchanging')} loading />;
    if (session.data) {
      return (
        <StatusScreen title={t('auth.magic.alreadyTitle')} text={t('auth.magic.alreadyText')}>
          <Button asChild>
            <Link to="/">{t('auth.magic.toCabinet')}</Link>
          </Button>
        </StatusScreen>
      );
    }
    // 422 — ссылка обрезана или испорчена: клиенту это «ссылка не действует», а не «проверьте поля», которых нет.
    return (
      <StatusScreen title={t('auth.magic.expiredTitle')} text={t('auth.magic.expiredText')}>
        <Button asChild>
          <Link to="/login">{t('auth.magic.requestAgain')}</Link>
        </Button>
      </StatusScreen>
    );
  }
  if (exchange.isError) {
    const closed = isPortalApiError(failure, 403);
    const transient = isPortalApiError(failure) && (failure.status === 0 || failure.status >= 500);
    return (
      <StatusScreen title={closed ? t('auth.magic.closedTitle') : t('auth.magic.failedTitle')} text={loginErrorText(failure, t)}>
        {transient ? <Button onClick={() => void exchange.refetch()}>{t('common.retry')}</Button> : null}
        {closed ? null : (
          <Button asChild variant={transient ? 'outline' : 'default'}>
            <Link to="/login">{t('auth.magic.requestAgain')}</Link>
          </Button>
        )}
      </StatusScreen>
    );
  }
  return <StatusScreen title={t('auth.magic.exchanging')} loading />;
}
