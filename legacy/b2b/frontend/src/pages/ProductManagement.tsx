import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Package, Eye, ShoppingCart, LayoutGrid, List,
} from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { StatusBadge, getStockVariant } from '@/components/ui/StatusBadge';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Checkbox } from '@/components/ui/checkbox';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';

import { useProducts, useDomainTypes, useStockStatuses, useManufacturers } from '@/hooks/useCatalog';
import type { Product } from '@/api/catalogApi';
import { getDomainLabelKey } from '@/config/domainConfig';
import { useUserStore } from '@/store/userStore';
import { useCartStore } from '@/store/cartStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';

interface ProductManagementProps {
  onProductClick?: (productId: string) => void;
}

export function ProductManagement({ onProductClick }: ProductManagementProps) {
  const { t } = useTranslation();
  const { activeStatus } = useUserStore();
  const cartStore = useCartStore();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const { data: domainTypes = [] } = useDomainTypes();
  const { data: stockStatuses = [] } = useStockStatuses();
  const { data: manufacturers = [] } = useManufacturers();

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [viewMode, setViewMode] = useState<'list' | 'grid'>(activeStatus === 'BUYER' ? 'grid' : 'list');

  const canSendRequest = activeStatus === 'BUYER';
  const showPrices = activeStatus === 'SELLER' || activeStatus === 'MANUFACTURER';

  const listParams = useListParams(['domain', 'stock', 'manufacturer'] as const, { defaultOrdering: 'name' });

  const apiParams = useMemo(() => {
    const p: Parameters<typeof useProducts>[0] = {};
    if (listParams.filters.domain !== 'all') p.domain_type = listParams.filters.domain;
    if (listParams.search.trim()) p.search = listParams.search.trim();
    if (listParams.filters.stock !== 'all') p.stock_status = listParams.filters.stock;
    if (listParams.filters.manufacturer !== 'all') p.manufacturer = Number(listParams.filters.manufacturer);
    return p;
  }, [listParams.filters, listParams.search]);

  const { data: products = [], isLoading } = useProducts(apiParams);

  const { items: paginated, total } = useMemo(
    () => applyListParams(products, listParams, {
      searchFields: () => [],
      sortAccessors: {
        name: (p) => p.name ?? '',
        sku: (p) => p.sku ?? '',
        price: (p) => Number(p.base_price) || 0,
        stock: (p) => p.stock_status ?? '',
      },
    }),
    [products, listParams.search, listParams.filters, listParams.ordering, listParams.page, listParams.pageSize],
  );

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedIds.size === paginated.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(paginated.map((p) => p.id)));
    }
  };

  const handleRowClick = (product: Product) => {
    onProductClick?.(String(product.id));
  };

  const stats = [
    { label: t('productManagement.kpi.totalItems'), value: String(products.length) },
    { label: t('productManagement.kpi.inStock'), value: String(products.filter(p => p.stock_status === 'IN_STOCK').length) },
    { label: t('productManagement.kpi.toOrder'), value: String(products.filter(p => p.stock_status === 'ON_ORDER').length) },
    ...(canSendRequest
      ? [{ label: t('productManagement.kpi.inCart'), value: String(cartStore.items.length) }]
      : [{ label: t('productManagement.kpi.sourcing'), value: String(products.filter(p => p.stock_status === 'EXPECTED').length) }]
    ),
  ];

  const pageTitle = {
    BUYER: t('productManagement.title.buyer'),
    MANUFACTURER: t('productManagement.title.manufacturer'),
    SELLER: t('productManagement.title.seller'),
  }[activeStatus];

  return (
    <PageShell
      title={pageTitle}
      description={activeStatus === 'BUYER' ? t('productManagement.subtitle.buyer') : activeStatus === 'MANUFACTURER' ? t('productManagement.subtitle.manufacturer') : t('productManagement.subtitle.seller')}
      icon={<Package className="h-5 w-5" />}
      stats={stats}
      actions={canSendRequest && selectedIds.size > 0 ? [{
        label: `${t('productManagement.createRequest')} (${selectedIds.size})`,
        onClick: () => {
          const selected = paginated.filter((p) => selectedIds.has(p.id));
          cartStore.addBulk(selected);
          cartStore.openCart();
          setSelectedIds(new Set());
        },
      }] : undefined}
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
            options: stockStatuses.map(s => ({ value: s.code, label: s.name })),
          },
          {
            key: 'manufacturer',
            value: listParams.filters.manufacturer,
            onChange: (v) => listParams.setFilter('manufacturer', v),
            allLabel: t('productManagement.filters.allManufacturers'),
            options: manufacturers.map(m => ({ value: String(m.id), label: m.name })),
          },
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

      {isLoading ? <LoadingRows rows={5} /> : products.length === 0 ? (
        <EmptyState icon={<Package className="h-5 w-5" />} message={t('productManagement.noResults')} />
      ) : viewMode === 'list' ? (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  {canSendRequest && (
                    <TableHead className="w-10">
                      <Checkbox checked={paginated.length > 0 && selectedIds.size === paginated.length} onCheckedChange={toggleAll} />
                    </TableHead>
                  )}
                  <SortableHead sortKey="name" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                    {t('productManagement.table.name')}
                  </SortableHead>
                  <SortableHead sortKey="sku" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                    {t('productManagement.table.article')}
                  </SortableHead>
                  <SortableHead sortKey="" current="" onChange={() => {}}>{t('productManagement.table.domain')}</SortableHead>
                  <SortableHead sortKey="" current="" onChange={() => {}}>{t('productManagement.table.category')}</SortableHead>
                  <SortableHead sortKey="" current="" onChange={() => {}}>{t('productManagement.table.uom')}</SortableHead>
                  {showPrices && (
                    <SortableHead sortKey="price" current={listParams.ordering} onChange={listParams.toggleOrdering} className="text-right">
                      {t('productManagement.table.priceFca')}
                    </SortableHead>
                  )}
                  <SortableHead sortKey="stock" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                    {t('productManagement.table.status')}
                  </SortableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginated.map((product) => (
                  <TableRow key={product.id} className="cursor-pointer" onClick={() => handleRowClick(product)}>
                    {canSendRequest && (
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <Checkbox checked={selectedIds.has(product.id)} onCheckedChange={() => toggleSelect(product.id)} />
                      </TableCell>
                    )}
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium text-sm">{product.name}</span>
                        {product.manufacturer_data?.name && (
                          <span className="text-xs text-muted-foreground">{product.manufacturer_data.name}</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-primary">{product.sku || ''}</TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="text-xs">{product.domain_type_name}</Badge>
                    </TableCell>
                    <TableCell className="text-sm">{product.category_data?.name || ''}</TableCell>
                    <TableCell className="text-sm">{product.uom_data?.name || ''}</TableCell>
                    {showPrices && (
                      <TableCell className="text-right font-medium tabular-nums text-sm">
                        {product.base_price && parseFloat(product.base_price) > 0
                          ? formatCurrency(parseFloat(product.base_price))
                          : ''}
                      </TableCell>
                    )}
                    <TableCell>
                      {product.stock_status && (
                        <StatusBadge
                          label={t(`productStatuses.${product.stock_status === 'IN_STOCK' ? 'in_stock' : product.stock_status === 'ON_ORDER' ? 'to_order' : product.stock_status === 'EXPECTED' ? 'sourcing' : 'inactive'}`)}
                          variant={getStockVariant(product.stock_status)}
                        />
                      )}
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => handleRowClick(product)}>
                        <Eye className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {paginated.map((product) => {
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
                        <Badge variant="secondary" className="text-xs">{product.domain_type_name}</Badge>
                        {product.stock_status && (
                          <StatusBadge
                            label={t(`productStatuses.${product.stock_status === 'IN_STOCK' ? 'in_stock' : product.stock_status === 'ON_ORDER' ? 'to_order' : product.stock_status === 'EXPECTED' ? 'sourcing' : 'inactive'}`)}
                            variant={getStockVariant(product.stock_status)}
                          />
                        )}
                      </div>
                    </div>
                    {canSendRequest && (
                      <div className="flex items-center shrink-0" onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant={isInCart ? 'secondary' : 'default'}
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => { if (!isInCart) cartStore.addItem(product); }}
                          disabled={isInCart}
                        >
                          <ShoppingCart className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
          <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
        </>
      )}
    </PageShell>
  );
}
