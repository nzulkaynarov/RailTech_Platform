import { useEffect, useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { loginErrorKey } from '@/api/errors';
import { exchangeMagicToken, isPortalApiError, type Me } from '@/api/portal';
import { StatusScreen } from '@/components/StatusScreen';
import { Button } from '@/components/ui/button';
import { ME_QUERY_KEY, afterSignIn } from '@/session/session';

/** Токен из фрагмента ссылки входа: `/auth/magic#token=…` — фрагмент не уходит на сервер и в журналы прокси. */
function tokenFromHash(hash: string): string {
  return new URLSearchParams(hash.replace(/^#/, '')).get('token')?.trim() ?? '';
}

/**
 * `/auth/magic#token=…` — ссылка из письма: токен берётся из фрагмента и уходит в теле
 * `POST /auth/magic {token}` → сессия → кабинет. Токен одноразовый, поэтому обмен — запрос React Query
 * с бесконечным сроком (повторный рендер или StrictMode не отправят его второй раз), а фрагмент сразу
 * убирается из адресной строки. 410 — «ссылка не действует», 403 — «доступ закрыт», 429 — «слишком много запросов».
 */
export function MagicLinkPage() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // Токен читается один раз: дальше фрагмент убирается из адреса, а обмен остаётся привязан к этому значению.
  const [token] = useState(() => tokenFromHash(location.hash));

  useEffect(() => {
    if (location.hash) navigate({ pathname: location.pathname, search: location.search, hash: '' }, { replace: true });
  }, [location.hash, location.pathname, location.search, navigate]);

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

  if (exchange.isSuccess) return <Navigate to="/" replace />;
  if (token === '' || exchange.isError) {
    const error = exchange.error;
    const expired = token === '' || isPortalApiError(error, 410);
    const closed = isPortalApiError(error, 403);
    return (
      <StatusScreen
        title={expired ? t('auth.magic.expiredTitle') : closed ? t('auth.magic.closedTitle') : t('auth.magic.failedTitle')}
        text={expired ? t('auth.magic.expiredText') : t(loginErrorKey(error))}
      >
        {closed ? null : (
          <Button asChild>
            <Link to="/login">{t('auth.magic.requestAgain')}</Link>
          </Button>
        )}
      </StatusScreen>
    );
  }
  return <StatusScreen title={t('auth.magic.exchanging')} loading />;
}

/**
 * Переходный период: старые письма ведут на `/auth/magic/<токен>` (токен в пути). Переносим токен во
 * фрагмент и дальше работает обычный обмен; маршрут уйдёт, когда ERP перестанет слать такие ссылки.
 */
export function LegacyMagicLinkRedirect() {
  const { token = '' } = useParams();
  return <Navigate to={{ pathname: '/auth/magic', hash: `#token=${encodeURIComponent(token)}` }} replace />;
}
