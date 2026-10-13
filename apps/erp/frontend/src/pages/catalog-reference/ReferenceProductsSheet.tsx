import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Package } from 'lucide-react';

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Pager } from '@/components/DataTable';
import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable';
import { useProductsPage } from '@/hooks/useCatalog';
import type { Product, ProductListParams } from '@/api/catalogApi';
import { LoadingRows, EmptyState, ErrorState } from '../shared/PageShell';

const PAGE_SIZE = 20;

/** Строка справочника, по которой открыт разрез каталога. */
export interface ReferenceTarget {
  title: string;
  params: Pick<ProductListParams, 'category' | 'equipment_groups'>;
}

interface ReferenceProductsSheetProps {
  target: ReferenceTarget;
  onClose: () => void;
}

/**
 * Разрез каталога по строке справочника (R6, D8).
 *
 * До этой волны карточка группы оборудования имела `cursor-pointer`, ховер и шеврон — и НЕ
 * имела обработчика: справочник обещал переход, которого не существовало. Бейджи подкатегорий
 * вели себя так же. Эталон (Odoo Product Categories, Shopify Collections, Google Merchant
 * Center): строка классификатора — это ссылка «покажи, что здесь лежит».
 *
 * Считает СЕРВЕР: фильтры `category` / `equipment_groups` и постраничка уже есть в
 * `ProductViewSet` (R1). Клиентская выборка поверх первой страницы врала бы так же, как
 * витрина до R1. Панель монтируется только на время показа — иначе справочник дёргал бы
 * список товаров при каждом открытии страницы.
 */
export function ReferenceProductsSheet({ target, onClose }: ReferenceProductsSheetProps) {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);

  const { data, isLoading, isError, refetch } = useProductsPage({
    ...target.params,
    page,
    page_size: PAGE_SIZE,
  });
  const rows: Product[] = data?.results ?? [];
  const total = data?.count ?? 0;

  const columns: ResponsiveColumn<Product>[] = [
    {
      id: 'name',
      header: t('productManagement.table.name'),
      mobileTitle: true,
      cell: (product) => (
        <div className="flex flex-col">
          <span className="font-medium">{product.name}</span>
          {product.manufacturer_part_number && (
            <span className="text-xs text-muted-foreground">{product.manufacturer_part_number}</span>
          )}
        </div>
      ),
    },
    {
      id: 'brand',
      header: t('catalogReference.products.brand'),
      cell: (product) => product.brand_name || '—',
    },
    {
      id: 'uom',
      header: t('productManagement.table.uom'),
      cell: (product) => product.uom_data?.name || '—',
      className: 'w-24',
    },
    {
      id: 'status',
      header: t('productManagement.table.status'),
      cell: (product) => <Badge variant="outline" className="text-xs">{product.status_name}</Badge>,
      className: 'w-32',
    },
  ];

  return (
    <Sheet open onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto p-0 sm:max-w-2xl">
        <SheetHeader className="border-b">
          <SheetTitle>{target.title}</SheetTitle>
          {/* `total`, а не `count`: `count` у i18next — служебный параметр множественного
              числа, и подпись начала бы искать несуществующие формы ключа. */}
          <SheetDescription>{t('catalogReference.products.subtitle', { total })}</SheetDescription>
        </SheetHeader>
        {isLoading ? (
          <LoadingRows rows={5} />
        ) : isError ? (
          <ErrorState onRetry={() => refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Package className="h-5 w-5" />}
            message={t('catalogReference.products.empty')}
            hint={t('catalogReference.products.emptyHint')}
          />
        ) : (
          <>
            <ResponsiveDataTable
              columns={columns}
              rows={rows}
              getRowId={(product) => product.id}
              // Прямое присвоение хэша — тот же приём, что у корзины и уведомлений: панель
              // живёт вне дерева страницы и своих пропсов навигации не имеет.
              onRowClick={(product) => { window.location.hash = `product_detail/${product.id}`; }}
            />
            <Pager page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

export default ReferenceProductsSheet;
