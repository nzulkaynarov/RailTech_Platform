import React, { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Package,
  PackageCheck,
  PackageSearch,
  PackageX,
  Search,
  SlidersHorizontal,
  ArrowUpDown,
  MoreVertical,
  Plus,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Eye,
  ShoppingCart,
  LayoutGrid,
  List,
  Check,
  Grid2X2,
  Grid3X3,
} from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { StatusBadge, getStockVariant } from '@/components/ui/StatusBadge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Checkbox } from '@/components/ui/checkbox';

import { useProducts, useDomainTypes } from '@/hooks/useCatalog';
import type { Product } from '@/api/catalogApi';
import { getDomainLabelKey } from '@/config/domainConfig';

import { useUserStore } from '@/store/userStore';
import { useCartStore } from '@/store/cartStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { cn } from '@/lib/utils';

const ITEMS_PER_PAGE_OPTIONS = [10, 20, 50];

// ─── KPI Card ──────────────────────────────────────────────────────────

interface KPICardProps {
  title: string;
  value: number;
  prevValue: number;
  icon: React.ReactNode;
  iconBg: string;
  isLoading?: boolean;
}

function KPICard({ title, value, prevValue, icon, iconBg, isLoading }: KPICardProps) {
  const { t } = useTranslation();

  if (isLoading) {
    return (
      <Card className="py-4 gap-2">
        <CardContent className="px-4">
          <div className="flex items-start justify-between">
            <div className="flex flex-col gap-1.5">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-6 w-16" />
              <Skeleton className="h-3 w-20" />
            </div>
            <Skeleton className="h-9 w-9 rounded-lg" />
          </div>
        </CardContent>
      </Card>
    );
  }

  const diff = value - prevValue;
  const pct = prevValue > 0 ? ((diff / prevValue) * 100).toFixed(1) : '0';
  const isUp = diff >= 0;

  return (
    <Card className="py-4 gap-2">
      <CardContent className="px-4">
        <div className="flex items-start justify-between">
          <div className="flex flex-col gap-1.5">
            <p className="text-xs font-medium text-muted-foreground">{title}</p>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold tabular-nums tracking-tight">
                {value.toLocaleString('ru-RU')}
              </span>
              <div className={`flex items-center gap-0.5 text-xs font-medium ${isUp ? 'text-success' : 'text-destructive'}`}>
                {isUp ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                {isUp ? '+' : ''}{pct}%
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              vs. {prevValue.toLocaleString('ru-RU')} {t('productManagement.prevPeriod')}
            </p>
          </div>
          <div className={`rounded-lg p-2 ${iconBg}`}>
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Stock Status Badge ────────────────────────────────────────────────

function StockStatusBadge({ status }: { status: string | null | undefined }) {
  const { t } = useTranslation();
  if (!status) return <Badge variant="secondary" className="text-xs">{t('productManagement.filters.unknown')}</Badge>;
  const labelMap: Record<string, string> = {
    IN_STOCK: 'productStatuses.in_stock',
    ON_ORDER: 'productStatuses.to_order',
    EXPECTED: 'productStatuses.sourcing',
    OUT_OF_STOCK: 'productStatuses.inactive',
  };
  return (
    <StatusBadge
      label={t(labelMap[status] ?? status)}
      variant={getStockVariant(status)}
    />
  );
}

function DomainBadge({ domainName }: { domainName: string }) {
  return (
    <Badge variant="secondary" className="text-xs font-medium">
      {domainName}
    </Badge>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────

interface ProductManagementProps {
  onProductClick?: (productId: string) => void;
}

type ViewMode = 'list' | 'grid';
type CardSize = 'compact' | 'normal' | 'large';

export function ProductManagement({ onProductClick }: ProductManagementProps) {
  const { t } = useTranslation();
  const { activeStatus, role } = useUserStore();
  const cartStore = useCartStore();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const { data: domainTypes = [] } = useDomainTypes();

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [domainFilter, setDomainFilter] = useState<string>('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [perPage, setPerPage] = useState(10);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [activeTab, setActiveTab] = useState('product_list');
  const [viewMode, setViewMode] = useState<ViewMode>(activeStatus === 'BUYER' ? 'grid' : 'list');
  const [cardSize, setCardSize] = useState<CardSize>('normal');

  /* ─── Fetch products from API ────────────────────────────────────── */
  const apiParams = useMemo(() => {
    const params: Parameters<typeof useProducts>[0] = {};
    if (domainFilter !== 'all') params.domain_type = domainFilter;
    if (search.trim()) params.search = search.trim();
    if (statusFilter !== 'all') params.stock_status = statusFilter;
    return params;
  }, [domainFilter, search, statusFilter]);

  const { data: products = [], isLoading } = useProducts(apiParams);

  /* ─── Client-side filtering & pagination ─────────────────────────── */
  const filtered = products;

  // KPI
  const totalProducts = products.length;
  const prevTotal = Math.max(1, totalProducts - 3);
  const inStockCount = products.filter((p) => p.stock_status === 'IN_STOCK').length;
  const prevInStock = Math.max(1, inStockCount - 2);
  const toOrderCount = products.filter((p) => p.stock_status === 'ON_ORDER').length;
  const prevToOrder = Math.max(1, toOrderCount - 1);
  const sourcingCount = products.filter((p) => p.stock_status === 'EXPECTED').length;
  const prevSourcing = Math.max(0, sourcingCount - 1);

  const totalPages = Math.ceil(filtered.length / perPage);
  const paginated = filtered.slice((currentPage - 1) * perPage, currentPage * perPage);

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
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

  /* ─── Status-aware labels ────────────────────────────────────────── */
  const pageTitle = {
    BUYER: t('productManagement.title.buyer'),
    MANUFACTURER: t('productManagement.title.manufacturer'),
    SELLER: t('productManagement.title.seller'),
  }[activeStatus];

  const canSendRequest = activeStatus === 'BUYER';
  const showPrices = activeStatus === 'SELLER' || activeStatus === 'MANUFACTURER';

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{pageTitle}</h1>
          {activeStatus === 'BUYER' && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {t('productManagement.subtitle.buyer')}
            </p>
          )}
          {activeStatus === 'MANUFACTURER' && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {t('productManagement.subtitle.manufacturer')}
            </p>
          )}
          {activeStatus === 'SELLER' && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {t('productManagement.subtitle.seller')}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {canSendRequest && (
              <Button
                className="gap-2"
                disabled={selectedIds.size === 0}
                onClick={() => {
                  const selectedProducts = paginated.filter((p) => selectedIds.has(p.id));
                  cartStore.addBulk(selectedProducts);
                  cartStore.openCart();
                  setSelectedIds(new Set());
                }}
              >
                <ShoppingCart className="h-4 w-4" />
                {t('productManagement.createRequest')} {selectedIds.size > 0 && `(${selectedIds.size})`}
              </Button>
          )}
        </div>
      </div>

      {/* Tabs — context-aware */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="product_list">
            {activeStatus === 'BUYER' ? t('productManagement.catalog') : t('productManagement.productList')}
          </TabsTrigger>
          {activeStatus !== 'BUYER' && (
            <TabsTrigger value="categories">{t('productManagement.categories')}</TabsTrigger>
          )}
          {activeStatus !== 'BUYER' && (
            <TabsTrigger value="equipment_groups">{t('productManagement.equipmentGroups')}</TabsTrigger>
          )}
        </TabsList>
      </Tabs>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          title={t('productManagement.kpi.totalItems')}
          value={totalProducts}
          prevValue={prevTotal}
          icon={<Package className="h-5 w-5 text-primary" />}
          iconBg="bg-primary/10"
          isLoading={isLoading}
        />
        <KPICard
          title={t('productManagement.kpi.inStock')}
          value={inStockCount}
          prevValue={prevInStock}
          icon={<PackageCheck className="h-5 w-5 text-success" />}
          iconBg="bg-success/10"
          isLoading={isLoading}
        />
        <KPICard
          title={t('productManagement.kpi.toOrder')}
          value={toOrderCount}
          prevValue={prevToOrder}
          icon={<PackageSearch className="h-5 w-5 text-warning" />}
          iconBg="bg-warning/10"
          isLoading={isLoading}
        />
        <KPICard
          title={activeStatus === 'BUYER' ? t('productManagement.kpi.inCart') : t('productManagement.kpi.sourcing')}
          value={activeStatus === 'BUYER' ? cartStore.items.length : sourcingCount}
          prevValue={activeStatus === 'BUYER' ? 0 : prevSourcing}
          icon={activeStatus === 'BUYER'
            ? <ShoppingCart className="h-5 w-5 text-primary" />
            : <PackageX className="h-5 w-5 text-primary" />
          }
          iconBg="bg-primary/10"
          isLoading={isLoading}
        />
      </div>

      {/* Filters + View Toggle */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={activeStatus === 'BUYER'
              ? t('productManagement.searchPlaceholder.buyer')
              : t('productManagement.searchPlaceholder.seller')}
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
                <SelectItem key={d.code} value={d.code}>
                  {t(getDomainLabelKey(d.code), d.name)}
                </SelectItem>
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
              {activeStatus !== 'BUYER' && <SelectItem value="OUT_OF_STOCK">{t('productManagement.filters.inactive')}</SelectItem>}
            </SelectContent>
          </Select>
          {canSendRequest && (
            <div className="flex items-center gap-2">
              <div className="flex items-center rounded-lg border p-0.5 gap-0.5">
                <Button
                  variant={viewMode === 'list' ? 'default' : 'ghost'}
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => setViewMode('list')}
                >
                  <List className="h-4 w-4" />
                </Button>
                <Button
                  variant={viewMode === 'grid' ? 'default' : 'ghost'}
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => setViewMode('grid')}
                >
                  <LayoutGrid className="h-4 w-4" />
                </Button>
              </div>
              {viewMode === 'grid' && (
                <div className="flex items-center rounded-lg border p-0.5 gap-0.5">
                  <Button
                    variant={cardSize === 'compact' ? 'default' : 'ghost'}
                    size="icon"
                    className="h-8 w-8"
                    title={t('productManagement.cardSize.compact')}
                    onClick={() => setCardSize('compact')}
                  >
                    <Grid3X3 className="h-4 w-4" />
                  </Button>
                  <Button
                    variant={cardSize === 'normal' ? 'default' : 'ghost'}
                    size="icon"
                    className="h-8 w-8"
                    title={t('productManagement.cardSize.normal')}
                    onClick={() => setCardSize('normal')}
                  >
                    <Grid2X2 className="h-4 w-4" />
                  </Button>
                  <Button
                    variant={cardSize === 'large' ? 'default' : 'ghost'}
                    size="icon"
                    className="h-8 w-8"
                    title={t('productManagement.cardSize.large')}
                    onClick={() => setCardSize('large')}
                  >
                    <LayoutGrid className="h-4 w-4" />
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Loading State */}
      {isLoading ? (
        <Card className="py-0 gap-0 overflow-hidden">
          <div className="p-6 space-y-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4">
                <Skeleton className="h-4 w-4" />
                <Skeleton className="h-4 w-48" />
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 w-16" />
              </div>
            ))}
          </div>
        </Card>
      ) : viewMode === 'list' ? (
        /* List View */
        <Card className="py-0 gap-0 overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40">
                <TableHead className="w-10">
                  <Checkbox
                    checked={paginated.length > 0 && selectedIds.size === paginated.length}
                    onCheckedChange={toggleAll}
                  />
                </TableHead>
                <TableHead>
                  <div className="flex items-center gap-1">{t('productManagement.table.name')} <ArrowUpDown className="h-3 w-3 text-muted-foreground" /></div>
                </TableHead>
                <TableHead>{t('productManagement.table.article')}</TableHead>
                <TableHead>{t('productManagement.table.gost')}</TableHead>
                <TableHead>{t('productManagement.table.domain')}</TableHead>
                <TableHead>{t('productManagement.table.category')}</TableHead>
                <TableHead>{t('productManagement.table.uom')}</TableHead>
                {showPrices && <TableHead className="text-right">{t('productManagement.table.priceFca')}</TableHead>}
                <TableHead>{t('productManagement.table.status')}</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginated.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={showPrices ? 10 : 9} className="h-32 text-center">
                    <div className="flex flex-col items-center gap-2 text-muted-foreground">
                      <PackageSearch className="h-8 w-8" />
                      <p className="text-sm">{t('productManagement.noResults')}</p>
                      <p className="text-xs">{t('productManagement.noResultsHint')}</p>
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                paginated.map((product) => (
                  <TableRow key={product.id} className="cursor-pointer" onClick={() => handleRowClick(product)}>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <Checkbox checked={selectedIds.has(product.id)} onCheckedChange={() => toggleSelect(product.id)} />
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium text-sm">{product.name}</span>
                        <span className="text-xs text-muted-foreground">
                          {product.manufacturer_data?.name ?? '—'}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-primary">{product.sku ?? '—'}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{product.gost_drawing ?? '—'}</TableCell>
                    <TableCell><DomainBadge domainName={product.domain_type_name} /></TableCell>
                    <TableCell className="text-sm">{product.category_data?.name ?? '—'}</TableCell>
                    <TableCell className="text-sm">{product.uom_data?.name ?? product.uom_data?.code ?? '—'}</TableCell>
                    {showPrices && (
                      <TableCell className="text-right font-medium tabular-nums text-sm">
                        {product.base_price && parseFloat(product.base_price) > 0
                          ? formatCurrency(parseFloat(product.base_price))
                          : <span className="text-muted-foreground">—</span>
                        }
                      </TableCell>
                    )}
                    <TableCell><StockStatusBadge status={product.stock_status} /></TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="h-8 w-8">
                            <MoreVertical className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={() => handleRowClick(product)}>
                            <Eye className="mr-2 h-4 w-4" /> {t('productManagement.actions.viewDetails')}
                          </DropdownMenuItem>
                          {canSendRequest && (
                            <DropdownMenuItem onClick={() => cartStore.addItem(product)}>
                              <ShoppingCart className="mr-2 h-4 w-4" /> {t('productManagement.actions.addToRequest')}
                            </DropdownMenuItem>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          {/* Pagination */}
          <div className="flex items-center justify-between border-t px-4 py-3">
            <div className="flex items-center gap-2">
              <Select value={String(perPage)} onValueChange={(v) => { setPerPage(Number(v)); setCurrentPage(1); }}>
                <SelectTrigger className="h-8 w-24">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ITEMS_PER_PAGE_OPTIONS.map((n) => (
                    <SelectItem key={n} value={String(n)}>{n} {t('productManagement.records')}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="outline" size="icon" className="h-8 w-8" disabled={currentPage === 1} onClick={() => setCurrentPage((p) => p - 1)}>
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
              <Button variant="outline" size="icon" className="h-8 w-8" disabled={currentPage === totalPages || totalPages === 0} onClick={() => setCurrentPage((p) => p + 1)}>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <span className="ml-2 text-xs text-muted-foreground">
                {filtered.length > 0 ? t('productManagement.paginationRange', { from: (currentPage - 1) * perPage + 1, to: Math.min(currentPage * perPage, filtered.length), total: filtered.length }) : t('productManagement.noRecords')}
              </span>
            </div>
          </div>
        </Card>
      ) : (
        // Grid View for BUYER
        <>
          {paginated.length === 0 ? (
            <Card className="h-64 flex items-center justify-center">
              <div className="flex flex-col items-center gap-2 text-muted-foreground">
                <PackageSearch className="h-8 w-8" />
                <p className="text-sm">{t('productManagement.noResults')}</p>
                <p className="text-xs">{t('productManagement.noResultsHint')}</p>
              </div>
            </Card>
          ) : (
            <>
              <div className={cn(
                'grid gap-4',
                cardSize === 'compact' ? 'grid-cols-4 lg:grid-cols-5' :
                cardSize === 'normal' ? 'grid-cols-3 lg:grid-cols-4' :
                'grid-cols-2 lg:grid-cols-3'
              )}>
                {paginated.map((product) => {
                  const isInCart = cartStore.items.some((i) => i.product.id === product.id);
                  const imageUrl = product.main_image_url || product.images?.[0]?.image_url;
                  return (
                    <Card key={product.id} className="overflow-hidden flex flex-col hover:shadow-lg transition-shadow cursor-pointer" onClick={() => handleRowClick(product)}>
                      {/* Image or Placeholder */}
                      <div className={cn(
                        'w-full flex items-center justify-center bg-muted',
                        cardSize === 'compact' ? 'h-20' : cardSize === 'normal' ? 'h-28' : 'h-40'
                      )}>
                        {imageUrl ? (
                          <img src={imageUrl} alt={product.name} className="w-full h-full object-cover" />
                        ) : (
                          <Package className={cn(
                            'text-muted-foreground',
                            cardSize === 'compact' ? 'h-8 w-8' : cardSize === 'normal' ? 'h-12 w-12' : 'h-16 w-16'
                          )} />
                        )}
                      </div>
                      <CardContent className={cn(
                        'flex flex-col gap-2',
                        cardSize === 'compact' ? 'p-2.5' : 'pt-4'
                      )}>
                        {/* Product Name */}
                        <div className="flex flex-col gap-0.5">
                          <h3 className={cn(
                            'font-bold line-clamp-2 leading-tight',
                            cardSize === 'compact' ? 'text-xs' : 'text-sm'
                          )}>
                            {product.name}
                          </h3>
                          <p className="text-xs text-muted-foreground">
                            {product.manufacturer_data?.name ?? '—'}
                          </p>
                        </div>

                        {/* GOST Badge — hide on compact */}
                        {cardSize !== 'compact' && product.gost_drawing && (
                          <Badge variant="outline" className="text-xs font-mono w-fit">
                            {product.gost_drawing}
                          </Badge>
                        )}

                        {/* Domain + Status Badges */}
                        <div className="flex items-center gap-1 flex-wrap">
                          <DomainBadge domainName={product.domain_type_name} />
                          {cardSize !== 'compact' && <StockStatusBadge status={product.stock_status} />}
                        </div>

                        {/* UOM — hide on compact */}
                        {cardSize !== 'compact' && product.uom_data && (
                          <div className="text-sm">
                            <span className="text-muted-foreground">{product.uom_data.name || product.uom_data.code}</span>
                          </div>
                        )}

                        {/* Add to Cart Button or Badge */}
                        {isInCart ? (
                          <Button
                            variant="default"
                            className={cn('w-full gap-1 pointer-events-none', cardSize === 'compact' ? 'h-7 text-xs' : '')}
                            disabled
                          >
                            <Check className="h-3 w-3" />
                            {t('productManagement.inRequest')}
                          </Button>
                        ) : (
                          <Button
                            className={cn('w-full gap-2', cardSize === 'compact' ? 'h-7 text-xs' : 'mt-1')}
                            onClick={(e) => {
                              e.stopPropagation();
                              cartStore.addItem(product);
                            }}
                          >
                            <Plus className={cardSize === 'compact' ? 'h-3 w-3' : 'h-4 w-4'} />
                            {cardSize === 'compact' ? t('productManagement.toRequest') : t('productManagement.addToRequest')}
                          </Button>
                        )}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>

              {/* Pagination */}
              <div className="flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-2">
                  <Select value={String(perPage)} onValueChange={(v) => { setPerPage(Number(v)); setCurrentPage(1); }}>
                    <SelectTrigger className="h-8 w-24">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ITEMS_PER_PAGE_OPTIONS.map((n) => (
                        <SelectItem key={n} value={String(n)}>{n} {t('productManagement.records')}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-center gap-1">
                  <Button variant="outline" size="icon" className="h-8 w-8" disabled={currentPage === 1} onClick={() => setCurrentPage((p) => p - 1)}>
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
                  <Button variant="outline" size="icon" className="h-8 w-8" disabled={currentPage === totalPages || totalPages === 0} onClick={() => setCurrentPage((p) => p + 1)}>
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                  <span className="ml-2 text-xs text-muted-foreground">
                    {filtered.length > 0 ? t('productManagement.paginationRange', { from: (currentPage - 1) * perPage + 1, to: Math.min(currentPage * perPage, filtered.length), total: filtered.length }) : t('productManagement.noRecords')}
                  </span>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
