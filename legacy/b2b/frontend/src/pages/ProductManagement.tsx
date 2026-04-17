import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Package, Search, SlidersHorizontal, ArrowUpDown, Eye,
  ShoppingCart, LayoutGrid, List, ChevronLeft, ChevronRight,
} from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { StatusBadge, getStockVariant } from '@/components/ui/StatusBadge';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';

import { useProducts, useDomainTypes } from '@/hooks/useCatalog';
import type { Product } from '@/api/catalogApi';
import { getDomainLabelKey } from '@/config/domainConfig';
import { useUserStore } from '@/store/userStore';
import { useCartStore } from '@/store/cartStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';

const PER_PAGE = 20;

/* ─── Main Component ─────────────────────────────────────────────────── */

interface ProductManagementProps {
  onProductClick?: (productId: string) => void;
}

export function ProductManagement({ onProductClick }: ProductManagementProps) {
  const { t } = useTranslation();
  const { activeStatus } = useUserStore();
  const cartStore = useCartStore();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const { data: domainTypes = [] } = useDomainTypes();

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [domainFilter, setDomainFilter] = useState<string>('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [viewMode, setViewMode] = useState<'list' | 'grid'>(activeStatus === 'BUYER' ? 'grid' : 'list');

  const apiParams = useMemo(() => {
    const params: Parameters<typeof useProducts>[0] = {};
    if (domainFilter !== 'all') params.domain_type = domainFilter;
    if (search.trim()) params.search = search.trim();
    if (statusFilter !== 'all') params.stock_status = statusFilter;
    return params;
  }, [domainFilter, search, statusFilter]);

  const { data: products = [], isLoading } = useProducts(apiParams);

  const totalPages = Math.ceil(products.length / PER_PAGE);
  const paginated = products.slice((currentPage - 1) * PER_PAGE, currentPage * PER_PAGE);

  const canSendRequest = activeStatus === 'BUYER';
  const showPrices = activeStatus === 'SELLER' || activeStatus === 'MANUFACTURER';

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
      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={canSendRequest ? t('productManagement.searchPlaceholder.buyer') : t('productManagement.searchPlaceholder.seller')}
            className="pl-9"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setCurrentPage(1); }}
          />
        </div>
        <div className="flex items-center gap-2">
          <Select value={domainFilter} onValueChange={(v) => { setDomainFilter(v); setCurrentPage(1); }}>
            <SelectTrigger className="w-44">
              <SelectValue placeholder={t('productManagement.filters.domain')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('productManagement.filters.allDomains')}</SelectItem>
              {domainTypes.map(d => (
                <SelectItem key={d.code} value={d.code}>{t(getDomainLabelKey(d.code), d.name)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setCurrentPage(1); }}>
            <SelectTrigger className="w-40">
              <SlidersHorizontal className="mr-2 h-4 w-4" />
              <SelectValue placeholder={t('productManagement.filters.status')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('productManagement.filters.allStatuses')}</SelectItem>
              <SelectItem value="IN_STOCK">{t('productManagement.filters.inStock')}</SelectItem>
              <SelectItem value="ON_ORDER">{t('productManagement.filters.toOrder')}</SelectItem>
              <SelectItem value="EXPECTED">{t('productManagement.filters.sourcing')}</SelectItem>
              {!canSendRequest && <SelectItem value="OUT_OF_STOCK">{t('productManagement.filters.inactive')}</SelectItem>}
            </SelectContent>
          </Select>
          <div className="flex items-center rounded-lg border p-0.5 gap-0.5">
            <Button variant={viewMode === 'list' ? 'default' : 'ghost'} size="icon" className="h-8 w-8" onClick={() => setViewMode('list')}>
              <List className="h-4 w-4" />
            </Button>
            <Button variant={viewMode === 'grid' ? 'default' : 'ghost'} size="icon" className="h-8 w-8" onClick={() => setViewMode('grid')}>
              <LayoutGrid className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>

      {/* Content */}
      {isLoading ? <LoadingRows rows={5} /> : products.length === 0 ? (
        <EmptyState icon={<Package className="h-5 w-5" />} message={t('productManagement.noResults')} />
      ) : viewMode === 'list' ? (
        /* ─── Table View ─── */
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
                  <TableHead>
                    <div className="flex items-center gap-1">{t('productManagement.table.name')} <ArrowUpDown className="h-3 w-3 text-muted-foreground" /></div>
                  </TableHead>
                  <TableHead>{t('productManagement.table.article')}</TableHead>
                  <TableHead>{t('productManagement.table.domain')}</TableHead>
                  <TableHead>{t('productManagement.table.category')}</TableHead>
                  <TableHead>{t('productManagement.table.uom')}</TableHead>
                  {showPrices && <TableHead className="text-right">{t('productManagement.table.priceFca')}</TableHead>}
                  <TableHead>{t('productManagement.table.status')}</TableHead>
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
          </CardContent>
        </Card>
      ) : (
        /* ─── Grid View ─── */
        <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {paginated.map((product) => {
            const imageUrl = product.main_image_url || product.images?.[0]?.image_url;
            const isInCart = cartStore.items.some((i) => i.product.id === product.id);
            return (
              <Card key={product.id} className="overflow-hidden hover:shadow-md transition-shadow cursor-pointer py-0 gap-0" onClick={() => handleRowClick(product)}>
                <CardContent className="flex gap-3 p-3">
                  {/* Compact image */}
                  <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg bg-muted overflow-hidden">
                    {imageUrl ? (
                      <img src={imageUrl} alt={product.name} className="h-full w-full object-cover" loading="lazy" />
                    ) : (
                      <Package className="h-6 w-6 text-muted-foreground" />
                    )}
                  </div>
                  {/* Info */}
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
                  {/* Action */}
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
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {t('productManagement.paginationRange', {
              from: (currentPage - 1) * PER_PAGE + 1,
              to: Math.min(currentPage * PER_PAGE, products.length),
              total: products.length,
            })}
          </p>
          <div className="flex items-center gap-1">
            <Button variant="outline" size="icon" className="h-8 w-8" disabled={currentPage === 1} onClick={() => setCurrentPage(p => p - 1)}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
              let page: number;
              if (totalPages <= 5) page = i + 1;
              else if (currentPage <= 3) page = i + 1;
              else if (currentPage >= totalPages - 2) page = totalPages - 4 + i;
              else page = currentPage - 2 + i;
              return (
                <Button key={page} variant={currentPage === page ? 'default' : 'outline'} size="icon" className="h-8 w-8" onClick={() => setCurrentPage(page)}>
                  {page}
                </Button>
              );
            })}
            <Button variant="outline" size="icon" className="h-8 w-8" disabled={currentPage === totalPages} onClick={() => setCurrentPage(p => p + 1)}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </PageShell>
  );
}
