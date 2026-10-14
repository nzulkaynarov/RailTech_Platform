import { useTranslation } from 'react-i18next';

import { StatusBadge, type BadgeVariant } from '@/components/ui/StatusBadge';
import { formatMoney } from '@/utils/decimal';
import type { PublishedCatalogItem } from '@/api/catalogApi';

const AVAILABILITY_VARIANT: Record<string, BadgeVariant> = {
  in_stock: 'success',
  expected: 'info',
  on_order: 'warning',
};

/**
 * «Глазами клиента» — сохранённая карточка так, как её отдаёт опубликованный слой сервера
 * (`client_preview` = `published_projection`). Не собирается на клиенте из формы: показывает
 * ровно то, что уйдёт клиенту, включая «по запросу» и скрытые фото.
 */
export function ClientPreview({ preview, published }: { preview: PublishedCatalogItem; published: boolean }) {
  const { t } = useTranslation();

  return (
    <div className="space-y-2 rounded-md border border-dashed p-3" aria-label={t('productEditor.preview.title')}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium text-muted-foreground">{t('productEditor.preview.title')}</p>
        {!published && (
          <StatusBadge label={t('productEditor.preview.notPublished')} variant="neutral" />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-0 break-words text-sm font-medium">{preview.name}</p>
        {preview.kind && <StatusBadge label={t(`productEditor.kind.${preview.kind}`)} variant="neutral" />}
        {preview.fulfillment_policy && (
          <StatusBadge label={t(`productEditor.policy.${preview.fulfillment_policy}`)} variant="neutral" />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        {preview.price ? (
          <span className="font-semibold tabular-nums">
            {formatMoney(preview.price.amount, preview.price.currency)}
            {preview.unit && <span className="font-normal text-muted-foreground"> / {preview.unit}</span>}
          </span>
        ) : (
          <span className="text-muted-foreground">{t('productEditor.preview.priceOnRequest')}</span>
        )}
        {preview.availability && (
          <StatusBadge
            label={t(`productEditor.preview.availability.${preview.availability}`)}
            variant={AVAILABILITY_VARIANT[preview.availability] ?? 'neutral'}
          />
        )}
        {preview.lead_time_days !== null && (
          <span className="text-muted-foreground">
            {t('productEditor.preview.leadTime', { count: preview.lead_time_days })}
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {t('productEditor.preview.media', { images: preview.images.length, documents: preview.documents.length })}
      </p>
    </div>
  );
}
