import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, Package, Plus, Tags } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { useCategories } from '@/hooks/useCatalog';
import { useMyCategoryRequests } from '@/hooks/useCategoryRequests';
import type { Category } from '@/api/catalogApi';
import type { CategoryRequest } from '@/api/categoryRequestsApi';
import { LoadingRows, EmptyState, ErrorState } from '../shared/PageShell';
import { CategoryRequestDialog } from './CategoryRequestDialog';
import { ReferenceProductsSheet, type ReferenceTarget } from './ReferenceProductsSheet';

/** Вариант бейджа статуса обращения — по КОДУ, не по подписи (Rule 2). */
const STATUS_VARIANT: Record<CategoryRequest['status'], 'secondary' | 'default' | 'destructive'> = {
  PENDING: 'secondary',
  APPROVED: 'default',
  REJECTED: 'destructive',
};

/**
 * Категории (R6): дерево платформы + escape-hatch «Предложить категорию» (D7) + переход
 * в товары категории (D8).
 *
 * Подпись раздела больше не обещает «управление деревом»: продавец им не управляет и не
 * управлял никогда — интерфейс просто врал (D7). Управление осталось у платформы (эталон
 * Google Merchant Center), а тупик закрыт обращением.
 */
export function CategoriesTab() {
  const { t } = useTranslation();
  const { data: categories, isLoading, isError, refetch } = useCategories();
  const { data: requests = [] } = useMyCategoryRequests();
  const [requestOpen, setRequestOpen] = useState(false);
  const [target, setTarget] = useState<ReferenceTarget | null>(null);

  const all = categories ?? [];
  const topLevel = all.filter((category: Category) => !category.parent);
  const childrenOf = (parentId: number) => all.filter((category: Category) => category.parent === parentId);

  const openProducts = (category: Category) =>
    setTarget({ title: category.name, params: { category: category.id } });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">{t('catalogReference.categories.hint')}</p>
        <Button size="sm" onClick={() => setRequestOpen(true)}>
          <Plus className="mr-2 h-4 w-4" aria-hidden="true" />
          {t('catalogReference.request.cta')}
        </Button>
      </div>

      {isLoading ? (
        <LoadingRows rows={4} />
      ) : isError ? (
        <ErrorState onRetry={() => refetch()} />
      ) : topLevel.length === 0 ? (
        <EmptyState
          icon={<Tags className="h-5 w-5" />}
          message={t('pages.common.noData')}
          hint={t('catalogReference.categories.emptyHint')}
          action={{ label: t('catalogReference.request.cta'), onClick: () => setRequestOpen(true) }}
        />
      ) : (
        <div className="space-y-2">
          {topLevel.map((category: Category, index: number) => {
            const children = childrenOf(category.id);
            return (
              <Collapsible key={category.id} defaultOpen={index === 0}>
                <Card className="border">
                  <CardContent className="p-0">
                    <div className="flex items-center justify-between gap-2 pr-3">
                      <CollapsibleTrigger asChild>
                        <Button variant="ghost" className="h-auto flex-1 justify-start gap-2 p-4 hover:bg-muted/50">
                          <ChevronDown className="h-4 w-4 transition-transform" aria-hidden="true" />
                          <span className="font-medium">{category.name}</span>
                          <Badge variant="outline" className="ml-2 text-xs">
                            {children.length} {t('pages.common.items')}
                          </Badge>
                        </Button>
                      </CollapsibleTrigger>
                      {/* D8: раньше строка выглядела кликабельной и не делала ничего.
                          Теперь переход существует и назван словами. */}
                      <Button variant="ghost" size="sm" onClick={() => openProducts(category)}>
                        <Package className="mr-2 h-4 w-4" aria-hidden="true" />
                        {t('catalogReference.showProducts')}
                      </Button>
                    </div>
                    <CollapsibleContent>
                      <div className="border-t bg-muted/30 p-4">
                        {children.length === 0 ? (
                          <p className="ml-4 text-xs text-muted-foreground">{t('pages.common.noData')}</p>
                        ) : (
                          <div className="ml-4 flex flex-wrap gap-2">
                            {children.map((child: Category) => (
                              <button
                                key={child.id}
                                type="button"
                                onClick={() => openProducts(child)}
                                className="rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              >
                                <Badge variant="secondary" className="cursor-pointer text-xs hover:bg-secondary/70">
                                  {child.name}
                                </Badge>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </CollapsibleContent>
                  </CardContent>
                </Card>
              </Collapsible>
            );
          })}
        </div>
      )}

      {requests.length > 0 && (
        <Card>
          <CardContent className="flex flex-col gap-3 p-4">
            <p className="text-sm font-medium">{t('catalogReference.request.myTitle')}</p>
            {requests.map((request) => (
              <div key={request.id} className="flex flex-wrap items-center justify-between gap-2 border-t pt-2 first:border-t-0 first:pt-0">
                <div className="flex min-w-0 flex-col">
                  <span className="text-sm">{request.proposed_name}</span>
                  {request.status === 'APPROVED' && request.resulting_category_name && (
                    <span className="text-xs text-muted-foreground">
                      {t('catalogReference.request.resulting', { name: request.resulting_category_name })}
                    </span>
                  )}
                  {request.status === 'REJECTED' && request.review_notes && (
                    <span className="text-xs text-muted-foreground">{request.review_notes}</span>
                  )}
                </div>
                <Badge variant={STATUS_VARIANT[request.status]} className="text-xs">
                  {t(`catalogReference.request.status.${request.status}`)}
                </Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <CategoryRequestDialog open={requestOpen} onOpenChange={setRequestOpen} parents={topLevel} />
      {target && <ReferenceProductsSheet target={target} onClose={() => setTarget(null)} />}
    </div>
  );
}

export default CategoriesTab;
