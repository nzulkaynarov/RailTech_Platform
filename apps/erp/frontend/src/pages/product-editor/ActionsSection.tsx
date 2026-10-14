import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Archive, ArchiveRestore, EyeOff, Send } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import {
  useArchiveProduct, usePublishProduct, useRestoreProduct, useUnpublishProduct,
} from '@/hooks/useCatalog';
import { extractApiErrorCode, translateApiError } from '@/lib/apiError';
import type { Product } from '@/api/catalogApi';

import { SECTION_IDS } from './anchors';

/**
 * Секция «Действия» — жизненный цикл карточки по ПРАВАМ, а не по роли (D9, ADR-0005):
 * `catalog.publish` → опубликовать/снять, `catalog.manage` → архив/восстановление.
 * Кнопки без права СКРЫТЫ, не задизейблены; авторитетная проверка живёт на сервере.
 * При неполноте «Опубликовать» disabled и перечисляет недостающее — тем же словарём
 * кодов, что рейка полноты.
 */
export function ActionsSection({ product }: { product: Product }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canPublish = useHasCompanyPermission('catalog.publish');
  const canManage = useHasCompanyPermission('catalog.manage');
  const publishMut = usePublishProduct();
  const unpublishMut = useUnpublishProduct();
  const archiveMut = useArchiveProduct();
  const restoreMut = useRestoreProduct();

  if (!canPublish && !canManage) return null;

  const statusCode = product.status_code ?? '';
  const completeness = product.completeness;
  const pending = publishMut.isPending || unpublishMut.isPending
    || archiveMut.isPending || restoreMut.isPending;
  const missingText = (completeness?.missing ?? [])
    .map((item) => t(`nomenclature.requirement.${item.code}`, { defaultValue: item.label }))
    .join(', ');

  const run = async (action: () => Promise<unknown>, successKey: string) => {
    try {
      await action();
      // Хуки инвалидируют списки (['products']); детальная карточка живёт под другим ключом.
      queryClient.invalidateQueries({ queryKey: ['product', String(product.id)] });
      toast.success(t(successKey));
    } catch (err) {
      toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('productEditor.actions.failed'));
    }
  };

  const showPublish = canPublish && statusCode !== 'PUBLISHED' && statusCode !== 'ARCHIVED';
  const publishBlockedByCompleteness = completeness ? !completeness.is_publishable : false;

  return (
    <section id={SECTION_IDS.actions} className="scroll-mt-20">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('productEditor.sections.actions')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {showPublish && (
              <Button
                size="sm"
                className="gap-1.5"
                disabled={pending || publishBlockedByCompleteness}
                onClick={() => run(() => publishMut.mutateAsync(product.id), 'productEditor.actions.published')}
              >
                <Send className="size-4" aria-hidden="true" />
                {t('nomenclature.publish')}
              </Button>
            )}
            {canPublish && statusCode === 'PUBLISHED' && (
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={pending}
                onClick={() => run(() => unpublishMut.mutateAsync(product.id), 'productEditor.actions.unpublished')}
              >
                <EyeOff className="size-4" aria-hidden="true" />
                {t('productEditor.actions.unpublish')}
              </Button>
            )}
            {canManage && statusCode !== 'ARCHIVED' && (
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={pending}
                onClick={() => run(() => archiveMut.mutateAsync(product.id), 'productEditor.actions.archived')}
              >
                <Archive className="size-4" aria-hidden="true" />
                {t('productEditor.actions.archive')}
              </Button>
            )}
            {canManage && statusCode === 'ARCHIVED' && (
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={pending}
                onClick={() => run(() => restoreMut.mutateAsync(product.id), 'productEditor.actions.restored')}
              >
                <ArchiveRestore className="size-4" aria-hidden="true" />
                {t('productEditor.actions.restore')}
              </Button>
            )}
          </div>
          {showPublish && publishBlockedByCompleteness && missingText && (
            <p className="text-xs text-muted-foreground">
              {t('productEditor.actions.publishBlocked', { fields: missingText })}
            </p>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
