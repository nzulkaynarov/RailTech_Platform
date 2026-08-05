import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Package, Eye, ShoppingCart, LayoutGrid, List, Pencil,
} from 'lucide-react';
import { ProductFormSheet } from './AdminCatalogPage';

import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { StatusBadge, getStockVariant } from '@/components/ui/StatusBadge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Checkbox } from '@/components/ui/checkbox';
import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable';
import { Toolbar, Pager, useListParams } from '@/components/DataTable';

import { useProductsPage, useDomainTypes, useStockStatuses, useManufacturers } from '@/hooks/useCatalog';
import type { Product, ProductListParams } from '@/api/catalogApi';
import { getDomainLabelKey } from '@/config/domainConfig';
import { uomLabelKey, stockStatusLabelKey } from '@/lib/codes';
import { useUserStore } from '@/store/userStore';
import { useAuthStore } from '@/store/authStore';
import { useCartStore } from '@/store/cartStore';
import { formatMoney } from '@/utils/decimal';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';

interface ProductManagementProps {
  onProductClick?: (productId: string) => void;
}

export function ProductManagement({ onProductClick }: ProductManagementProps) {
  const { t } = useTranslation();
  const { activeStatus } = useUserStore();
  const sellerCompanyId = useAuthStore((s) => s.user?.company?.id);
  const cartStore = useCartStore();
  const { data: domainTypes = [] } = useDomainTypes();
  const { data: stockStatuses = [] } = useStockStatuses();
  const { data: manufacturers = [] } = useManufacturers();

  // Выбор хранится КАРТОЧКАМИ, а не идентификаторами: страница теперь приходит с сервера,
  // и по набору id с прошлой страницы объект уже не найти — «Создать заявку» молча клала
  // в корзину только то, что видно сейчас.
  const [selected, setSelected] = useState<Map<number, Product>>(new Map());
  const [viewMode, setViewMode] = useState<'list' | 'grid'>(activeStatus === 'BUYER' ? 'grid' : 'list');
  const [editTarget, setEditTarget] = useState<Product | null>(null);
  const [editSheetOpen, setEditSheetOpen] = useState(false);

  const canSendRequest = activeStatus === 'BUYER';
  const showPrices = activeStatus === 'SELLER';
  const canManageCatalog = activeStatus === 'SELLER';

  const listParams = useListParams(['domain', 'stock', 'brand', 'owner'] as const, { defaultOrdering: 'name' });

  const apiParams = useMemo(() => {
    const params: ProductListParams = {
      page: listParams.page,
      page_size: listParams.pageSize,
    };
    if (listParams.filters.domain !== 'all') params.domain_type = listParams.filters.domain;
    if (listParams.search.trim()) params.search = listParams.search.trim();
    if (listParams.filters.stock !== 'all') params.stock_status = listParams.filters.stock;
    if (listParams.filters.brand !== 'all') params.brand = Number(listParams.filters.brand);
    // «Только мои» есть лишь у того, кто ведёт каталог: у покупателя своих карточек нет.
    if (canManageCatalog && listParams.filters.owner === 'mine') params.mine = true;
    // Сортировку считает СЕРВЕР. Сортировать страницу из 20 строк и называть это
    // сортировкой каталога — та же ложь, что и клиентская постраничка (R1).
    if (listParams.ordering) params.ordering = listParams.ordering;
    return params;
  }, [
    listParams.filters, listParams.search, listParams.ordering,
    listParams.page, listParams.pageSize, canManageCatalog,
  ]);

  const { data, isLoading, isError, refetch } = useProductsPage(apiParams);
  const rows: Product[] = data?.results ?? [];
  const total = data?.count ?? 0;

  const toggleSelect = (product: Product) => {
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(product.id)) next.delete(product.id); else next.set(product.id, product);
      return next;
    });
  };

  const allOnPageSelected = rows.length > 0 && rows.every((product) => selected.has(product.id));

  const toggleAll = () => {
    setSelected((prev) => {
      const next = new Map(prev);
      if (allOnPageSelected) {
        rows.forEach((product) => next.delete(product.id));
      } else {
        rows.forEach((product) => next.set(product.id, product));
      }
      return next;
    });
  };

  const handleRowClick = (product: Product) => {
    onProductClick?.(String(product.id));
  };

  // Плиток «В наличии / Под заказ / На поиске» здесь БОЛЬШЕ НЕТ. Считать их можно было
  // только по загруженному массиву, а он теперь — одна страница: плитка печатала бы
  // «в наличии на этой странице» и называла это каталогом. Тот же вопрос точно
  // отвечает фильтр наличия в тулбаре: выбери статус — «Всего позиций» и есть ответ.
  // «Всего позиций» — `count` отфильтрованной выборки с сервера, а не длина страницы.
  const stats = [
    { label: t('productManagement.kpi.totalItems'), value: String(total) },
    ...(canSendRequest
      ? [{ label: t('productManagement.kpi.inCart'), value: String(cartStore.items.length) }]
      : []
    ),
  ];

  const pageTitle = {
    BUYER: t('productManagement.title.buyer'),
    MANUFACTURER: t('productManagement.title.manufacturer'),
    SELLER: t('productManagement.title.seller'),
  }[activeStatus];

  const stockBadge = (product: Product) => {
    const labelKey = stockStatusLabelKey(product.stock_status);
    // Ни статуса, ни подписи — значит, оффера нет вовсе. Раньше в плиточном виде
    // такая карточка получала бейдж «Под заказ»: витрина обещала доступность там,
    // где не было ни одного предложения.
    if (!labelKey || !product.stock_status) return null;
    return <StatusBadge label={t(labelKey)} variant={getStockVariant(product.stock_status)} />;
  };

  const columns: ResponsiveColumn<Product>[] = [
    ...(canSendRequest
      ? [{
          id: 'select',
          className: 'w-10',
          header: (
            <Checkbox
              checked={allOnPageSelected}
              onCheckedChange={toggleAll}
              aria-label={t('productManagement.table.select')}
            />
          ),
          mobileLabel: t('productManagement.table.select'),
          cell: (product: Product) => (
            <Checkbox
              checked={selected.has(product.id)}
              onCheckedChange={() => toggleSelect(product)}
              aria-label={product.name}
            />
          ),
        }]
      : []),
    {
      // Сортируемы ровно те колонки, которые умеет сортировать сервер (`name`, `sku`).
      // Заголовок со стрелкой, который ничего не делает, — дефект того же класса.
      id: 'name', sortKey: 'name', header: t('productManagement.table.name'), mobileTitle: true,
      cell: (product) => (
        <div className="flex flex-col">
          <span className="text-sm font-medium">{product.name}</span>
          {product.brand_name && (
            <span className="text-xs text-muted-foreground">{product.brand_name}</span>
          )}
        </div>
      ),
    },
    {
      id: 'sku', sortKey: 'sku', header: t('productManagement.table.article'),
      className: 'font-mono text-xs text-primary',
      cell: (product) => product.sku || '',
    },
    {
      id: 'domain', header: t('productManagement.table.domain'),
      cell: (product) => (
        <Badge variant="secondary" className="text-xs">
          {t(getDomainLabelKey(product.domain_type_code ?? ''), product.domain_type_name)}
        </Badge>
      ),
    },
    {
      id: 'category', header: t('productManagement.table.category'), className: 'text-sm',
      cell: (product) => product.category_data?.name || '',
    },
    {
      id: 'uom', header: t('productManagement.table.uom'), className: 'text-sm',
      cell: (product) => (product.uom_data
        ? (uomLabelKey(product.uom_data.code) ? t(uomLabelKey(product.uom_data.code)) : product.uom_data.name)
        : ''),
    },
    ...(canManageCatalog
      ? [{
          // D12: до этой волны продавец видел ВЕСЬ опубликованный каталог рынка вперемешку
          // со своими черновиками и никак не мог понять, чья перед ним карточка.
          id: 'owner',
          header: t('productManagement.table.owner'),
          className: 'whitespace-nowrap',
          cell: (product: Product) => {
            const owner = product.owner_company_data;
            if (!owner) return null;
            const isMine = sellerCompanyId != null && owner.id === sellerCompanyId;
            return (
              <span className="inline-flex items-center gap-1.5">
                <span className="text-sm">{owner.name}</span>
                {isMine && (
                  <Badge variant="secondary" className="text-xs">{t('productManagement.table.mine')}</Badge>
                )}
              </span>
            );
          },
        }]
      : []),
    ...(showPrices
      ? [{
          id: 'price',
          header: t('productManagement.table.priceFca'),
          className: 'text-right font-medium tabular-nums text-sm',
          cell: (product: Product) => {
            // Цены нет вовсе (нет оффера) либо её срезал cost-gate у чужой карточки —
            // пустая ячейка. Печатать здесь 0 значило бы придумать нулевой ценник.
            if (!product.base_price) return null;
            // Валюта — ТОГО ЖЕ оффера. Раньше здесь стояло жёсткое 'UZS', и оффер
            // в долларах печатался суммами.
            return product.base_price_currency
              ? formatMoney(product.base_price, product.base_price_currency)
              : product.base_price;
          },
        }]
      : []),
    {
      // `whitespace-nowrap` не косметика. Колонок стало больше (добавился владелец), таблица
      // ужалась ровно в ширину карточки, и бейдж наличия обрезался ВНУТРИ своей ячейки —
      // «В наличии» читалось как «В наличи», причём молча. Запрет переноса заставляет таблицу
      // вырасти, и она честно прокручивается в собственной обёртке shadcn `Table`.
      // Поймано проходом глазами: ни один тест ширину текста не меряет.
      id: 'stock', header: t('productManagement.table.status'), className: 'whitespace-nowrap',
      cell: (product) => stockBadge(product),
    },
    {
      id: 'actions', header: t('productManagement.table.actions'), className: 'w-10', mobileActions: true,
      cell: (product) => (
        <div className="flex items-center gap-1" data-row-action>
          {canSendRequest && (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              aria-label={t('catalog.card.requestQuote')}
              onClick={() => { cartStore.addItem(product); toast.success(t('cart.added', { name: product.name })); }}
            >
              <ShoppingCart className="h-4 w-4" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={t('common.open')}
            onClick={() => handleRowClick(product)}
          >
            <Eye className="h-4 w-4" />
          </Button>
          {canManageCatalog && (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              aria-label={t('common.edit')}
              onClick={() => { setEditTarget(product); setEditSheetOpen(true); }}
            >
              <Pencil className="h-4 w-4" />
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <PageShell
      title={pageTitle}
      description={activeStatus === 'BUYER' ? t('productManagement.subtitle.buyer') : t('productManagement.subtitle.seller')}
      icon={<Package className="h-5 w-5" />}
      stats={stats}
      actions={
        canSendRequest && selected.size > 0
          ? [{
              label: `${t('productManagement.createRequest')} (${selected.size})`,
              onClick: () => {
                cartStore.addBulk([...selected.values()]);
                cartStore.openCart();
                setSelected(new Map());
              },
            }]
          : canManageCatalog
            ? [
                {
                  label: t('productManagement.bulkImport'),
                  variant: 'outline' as const,
                  onClick: () => {
                    // Catalog/PIM bulk import — distinct from the deal-RFQ Excel
                    // importer, which now lives inline in the request flow.
                    window.location.hash = 'catalog-import';
                  },
                },
                {
                  label: t('productManagement.addProduct'),
                  onClick: () => {
                    setEditTarget(null);
                    setEditSheetOpen(true);
                  },
                },
              ]
            : undefined
      }
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={canSendRequest ? t('productManagement.searchPlaceholder.buyer') : t('productManagement.searchPlaceholder.seller')}
        filters={[
          {
            key: 'domain',
            value: listParams.filters.domain,
            onChange: (v) => listParams.setFilter('domain', v),
            allLabel: t('productManagement.filters.allDomains'),
            options: domainTypes.map(d => ({ value: d.code, label: t(getDomainLabelKey(d.code), d.name) })),
          },
          {
            key: 'stock',
            value: listParams.filters.stock,
            onChange: (v) => listParams.setFilter('stock', v),
            allLabel: t('productManagement.filters.allStatuses'),
            // Подпись по КОДУ: русское имя из справочника остаётся фолбэком
            // для кодов, которых эта сборка ещё не знает.
            options: stockStatuses.map(s => ({
              value: s.code,
              label: stockStatusLabelKey(s.code) ? t(stockStatusLabelKey(s.code)) : s.name,
            })),
          },
          {
            key: 'brand',
            value: listParams.filters.brand,
            onChange: (v) => listParams.setFilter('brand', v),
            allLabel: t('productManagement.filters.allManufacturers'),
            options: manufacturers.map(m => ({ value: String(m.id), label: m.name })),
          },
          ...(canManageCatalog
            ? [{
                key: 'owner',
                value: listParams.filters.owner,
                onChange: (v: string) => listParams.setFilter('owner', v),
                allLabel: t('productManagement.filters.allOwners'),
                options: [{ value: 'mine', label: t('productManagement.filters.onlyMine') }],
              }]
            : []),
        ]}
        extra={
          <div className="flex items-center rounded-lg border p-0.5 gap-0.5">
            <Button variant={viewMode === 'list' ? 'default' : 'ghost'} size="icon" className="h-8 w-8" onClick={() => setViewMode('list')}>
              <List className="h-4 w-4" />
            </Button>
            <Button variant={viewMode === 'grid' ? 'default' : 'ghost'} size="icon" className="h-8 w-8" onClick={() => setViewMode('grid')}>
              <LayoutGrid className="h-4 w-4" />
            </Button>
          </div>
        }
      />

      {isLoading ? <LoadingRows rows={5} /> : isError ? (
        <ErrorState onRetry={refetch} />
      ) : rows.length === 0 ? (
        <EmptyState icon={<Package className="h-5 w-5" />} message={t('productManagement.noResults')} />
      ) : viewMode === 'list' ? (
        <Card>
          <CardContent className="p-0">
            <ResponsiveDataTable
              columns={columns}
              rows={rows}
              getRowId={(product) => product.id}
              onRowClick={handleRowClick}
              sorting={{ ordering: listParams.ordering, onToggle: listParams.toggleOrdering }}
            />
            <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {rows.map((product) => {
              const imageUrl = product.main_image_url || product.images?.[0]?.image_url;
              const isInCart = cartStore.items.some((i) => i.product.id === product.id);
              return (
                <Card key={product.id} className="overflow-hidden hover:shadow-md transition-shadow cursor-pointer py-0 gap-0" onClick={() => handleRowClick(product)}>
                  <CardContent className="flex gap-3 p-3">
                    <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg bg-muted overflow-hidden">
                      {imageUrl ? (
                        <img src={imageUrl} alt={product.name} className="h-full w-full object-cover" loading="lazy" />
                      ) : (
                        <Package className="h-6 w-6 text-muted-foreground" />
                      )}
                    </div>
                    <div className="flex flex-col gap-1 min-w-0 flex-1">
                      <h3 className="text-sm font-semibold line-clamp-2 leading-tight">{product.name}</h3>
                      {product.sku && (
                        <p className="text-xs text-muted-foreground font-mono">{product.sku}</p>
                      )}
                      <div className="flex items-center gap-1 flex-wrap mt-auto">
                        <Badge variant="secondary" className="text-xs">{t(getDomainLabelKey(product.domain_type_code ?? ''), product.domain_type_name)}</Badge>
                        {stockBadge(product)}
                      </div>
                    </div>
                    {canSendRequest && (
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <div className="flex items-center shrink-0" onClick={(e) => e.stopPropagation()}>
                              <Button
                                variant={isInCart ? 'secondary' : 'default'}
                                size="icon"
                                className="h-8 w-8"
                                aria-label={isInCart ? t('cart.addedToCart') : t('catalog.card.requestQuote')}
                                onClick={() => {
                                  if (isInCart) return;
                                  cartStore.addItem(product);
                                  toast.success(t('cart.added', { name: product.name }));
                                }}
                                disabled={isInCart}
                              >
                                <ShoppingCart className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </TooltipTrigger>
                          <TooltipContent>
                            {isInCart ? t('cart.addedToCart') : t('catalog.card.requestQuote')}
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
          <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
        </>
      )}

      {canManageCatalog && (
        <ProductFormSheet
          open={editSheetOpen}
          onOpenChange={setEditSheetOpen}
          target={editTarget}
          sellerCompanyId={sellerCompanyId}
        />
      )}
    </PageShell>
  );
}
