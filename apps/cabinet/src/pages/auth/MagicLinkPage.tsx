import { Link, Navigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { apiErrorKey } from '@/api/errors';
import { exchangeMagicLink, isPortalApiError, type Me } from '@/api/portal';
import { StatusScreen } from '@/components/StatusScreen';
import { Button } from '@/components/ui/button';
import { ME_QUERY_KEY, afterSignIn } from '@/session/session';

/**
 * `/auth/magic/:token` — ссылка из письма: `GET /auth/magic/{token}` → сессия → кабинет.
 * Ссылка одноразовая, поэтому обмен — запрос React Query с бесконечным сроком (повторный
 * рендер или StrictMode не отправят токен второй раз). 410 — «ссылка не действует».
 */
export function MagicLinkPage() {
  const { t } = useTranslation();
  const { token = '' } = useParams();
  const queryClient = useQueryClient();

  const exchange = useQuery({
    queryKey: ['magic-link', token],
    queryFn: async () => {
      const me = afterSignIn(await exchangeMagicLink(token));
      queryClient.setQueryData<Me | null>(ME_QUERY_KEY, me);
      return me;
    },
    retry: false,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
  });

  if (exchange.isSuccess) return <Navigate to="/" replace />;
  if (exchange.isError) {
    const expired = isPortalApiError(exchange.error, 410);
    return (
      <StatusScreen
        title={t('auth.magic.expiredTitle')}
        text={expired ? t('auth.magic.expiredText') : t(apiErrorKey(exchange.error))}
      >
        <Button asChild>
          <Link to="/login">{t('auth.magic.requestAgain')}</Link>
        </Button>
      </StatusScreen>
    );
  }
  return <StatusScreen title={t('auth.magic.exchanging')} loading />;
}
