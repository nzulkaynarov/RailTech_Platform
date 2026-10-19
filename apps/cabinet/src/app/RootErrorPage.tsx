import { useEffect } from 'react';
import { isRouteErrorResponse, useRouteError } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { StatusScreen } from '@/components/StatusScreen';
import { Button } from '@/components/ui/button';

/**
 * Корневой `errorElement`: исключение при отрисовке или в загрузчике маршрута не оставляет белый экран —
 * клиент видит понятный текст и кнопки «Обновить» / «На главную». Подробности ошибки — только в консоль.
 */
export function RootErrorPage() {
  const { t } = useTranslation();
  const error = useRouteError();
  const notFound = isRouteErrorResponse(error) && error.status === 404;

  useEffect(() => {
    if (!notFound) console.error('Cabinet: ошибка маршрута', error);
  }, [error, notFound]);

  return (
    <StatusScreen
      title={notFound ? t('common.notFoundTitle') : t('common.crashTitle')}
      text={notFound ? t('common.notFoundText') : t('common.crashText')}
    >
      {notFound ? null : <Button onClick={() => window.location.reload()}>{t('common.reload')}</Button>}
      <Button variant="outline" onClick={() => window.location.assign('/')}>
        {t('common.home')}
      </Button>
    </StatusScreen>
  );
}
