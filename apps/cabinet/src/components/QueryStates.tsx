import { useTranslation } from 'react-i18next';
import { AlertTriangle, RotateCw } from 'lucide-react';

import { apiErrorKey } from '@/api/errors';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';

/** Скелетон списка: несколько карточек-заглушек; для дикторов — «Загрузка…». */
export function ListSkeleton({ rows = 3 }: { rows?: number }) {
  const { t } = useTranslation();
  return (
    <div role="status" aria-live="polite" aria-busy="true" className="flex flex-col gap-3">
      <span className="sr-only">{t('common.loading')}</span>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex flex-col gap-2 rounded-lg border bg-card p-4">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-3 w-1/2" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      ))}
    </div>
  );
}

/** Скелетон карточки объекта (КП, позиция каталога). */
export function DetailSkeleton() {
  const { t } = useTranslation();
  return (
    <div role="status" aria-live="polite" aria-busy="true" className="flex flex-col gap-4">
      <span className="sr-only">{t('common.loading')}</span>
      <Skeleton className="h-6 w-1/2" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-40 w-full" />
    </div>
  );
}

/**
 * Ошибка загрузки: код `detail` → текст `apiErrors.*` (404 — «не найдено» без намёка на чужую
 * компанию), кнопка «Повторить». 401 сюда не доходит — его разбирает сессия (queryClient).
 */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <Alert variant="destructive">
      <AlertTriangle aria-hidden="true" />
      <AlertTitle>{t('common.loadFailed')}</AlertTitle>
      <AlertDescription>
        <p>{t(apiErrorKey(error))}</p>
        {onRetry ? (
          <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
            <RotateCw aria-hidden="true" />
            {t('common.retry')}
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
