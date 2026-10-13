import { useTranslation } from 'react-i18next';
import { MoreHorizontal } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useCatalogPublishGate } from '@/hooks/useCatalogPublishGate';
import { useArchiveProduct, usePublishProduct, useRestoreProduct, useUnpublishProduct } from '@/hooks/useCatalog';
import { extractApiErrorCode, translateApiError } from '@/lib/apiError';
import type { Product } from '@/api/catalogApi';
import type { MyProductsTabKey } from './tabs';

/**
 * Действия строки по табам единого реестра (R2, аудит §5.2):
 * кандидаты/черновики — «Дополнить» (страница-редактор) + «Опубликовать»;
 * опубликовано — «Открыть» + меню «Снять с публикации» / «В архив»;
 * архив — «Восстановить» (архив ОБРАТИМ — закрывает D10 «чёрную дыру»).
 *
 * KYC-гейт действует ТОЛЬКО на публикацию: снятие с витрины, архив и восстановление
 * бэкенд сознательно разрешает до верификации — наводить порядок можно всегда.
 */
export function RowActions({
  product,
  tab,
  onEnrich,
  onOpen,
}: {
  product: Product;
  tab: MyProductsTabKey;
  onEnrich: (product: Product) => void;
  onOpen: (product: Product) => void;
}) {
  const { t } = useTranslation();
  const publishGate = useCatalogPublishGate();
  const publishOne = usePublishProduct();
  const unpublishOne = useUnpublishProduct();
  const archiveOne = useArchiveProduct();
  const restoreOne = useRestoreProduct();

  const actionError = (err: unknown) =>
    toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('myProducts.actionFailed'));

  if (tab === 'CANDIDATES' || tab === 'DRAFTS') {
    return (
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => onEnrich(product)}>
          {t('nomenclature.enrich')}
        </Button>
        <Button
          size="sm"
          title={publishGate.blocked ? t('nomenclature.publishNeedsKyc') : undefined}
          disabled={!product.completeness?.is_publishable || publishOne.isPending || publishGate.blocked}
          onClick={() =>
            publishOne.mutate(product.id, {
              onSuccess: () => toast.success(t('nomenclature.published', { name: product.name })),
              onError: (err) =>
                toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('nomenclature.publishFailed')),
            })
          }
        >
          {t('nomenclature.publish')}
        </Button>
      </div>
    );
  }

  if (tab === 'PUBLISHED') {
    return (
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="sm" onClick={() => onOpen(product)}>
          {t('nomenclature.open')}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={t('myProducts.rowMenu')}>
              <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem
              disabled={unpublishOne.isPending}
              onClick={() =>
                unpublishOne.mutate(product.id, {
                  onSuccess: () => toast.success(t('myProducts.unpublished', { name: product.name })),
                  onError: actionError,
                })
              }
            >
              {t('myProducts.unpublish')}
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={archiveOne.isPending}
              onClick={() =>
                archiveOne.mutate(product.id, {
                  onSuccess: () => toast.success(t('myProducts.archivedOne', { name: product.name })),
                  onError: actionError,
                })
              }
            >
              {t('myProducts.archive')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    );
  }

  return (
    <Button
      variant="outline"
      size="sm"
      disabled={restoreOne.isPending}
      onClick={() =>
        restoreOne.mutate(product.id, {
          onSuccess: () => toast.success(t('myProducts.restored', { name: product.name })),
          onError: actionError,
        })
      }
    >
      {t('myProducts.restore')}
    </Button>
  );
}
