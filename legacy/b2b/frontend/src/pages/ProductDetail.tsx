import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft, ShoppingCart, Minus, Plus, Package,
} from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table';
import { StatusBadge, getStockVariant } from '@/components/ui/StatusBadge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Breadcrumb, BreadcrumbItem, BreadcrumbLink,
  BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';

import { useProduct } from '@/hooks/useCatalog';
import { useCartStore } from '@/store/cartStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { useUserStore } from '@/store/userStore';
import { getDomainLabelKey } from '@/config/domainConfig';

/* ─── Main Component ─────────────────────────────────────────────────── */

interface ProductDetailProps {
  productId: string;
  onBack: () => void;
  onNavigate: (productId: string) => void;
}

export function ProductDetail({ productId, onBack }: ProductDetailProps) {
  const { t } = useTranslation();
  const { addItem, openCart } = useCartStore();
  const formatCurrency = useCurrencyStore((s) => s.format);
  const { activeStatus } = useUserStore();
  const canSendRequest = activeStatus === 'BUYER';
  const showPrices = activeStatus === 'SELLER' || activeStatus === 'MANUFACTURER';

  const { data: product, isLoading, error } = useProduct(productId);
  const [qty, setQty] = useState(1);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Skeleton className="aspect-square rounded-xl" />
          <div className="space-y-4">
            <Skeleton className="h-8 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        </div>
      </div>
    );
  }

  if (error || !product) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3">
        <Package className="h-12 w-12 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">{error instanceof Error ? error.message : t('catalog.productNotFound')}</p>
        <Button variant="outline" onClick={onBack}>{t('common.back')}</Button>
      </div>
    );
  }

  const imageUrl = product.main_image_url || product.images?.[0]?.image_url;
  const specs = product.specifications ?? {};
  const specEntries = Object.entries(specs).filter(([, v]) => v != null && v !== '');

  const stockStatusKey = product.stock_status === 'IN_STOCK' ? 'in_stock'
    : product.stock_status === 'ON_ORDER' ? 'to_order'
    : product.stock_status === 'EXPECTED' ? 'sourcing' : 'inactive';

  const attributes = [
    { label: t('productDetail.article'), value: product.sku },
    { label: t('productDetail.gostDrawing'), value: product.gost_drawing },
    { label: t('productDetail.uom'), value: product.uom_data?.name },
    { label: t('productDetail.manufacturer'), value: product.manufacturer_data?.name },
    { label: t('productDetail.category'), value: product.category_data?.name },
    { label: t('productDetail.domain'), value: product.domain_type_name ? t(getDomainLabelKey(product.domain_type_code ?? ''), product.domain_type_name) : undefined },
  ].filter(a => a.value);

  return (
    <div className="flex flex-col gap-6">
      {/* Breadcrumb */}
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="#" onClick={(e) => { e.preventDefault(); onBack(); }}>
              {t('catalog.title')}
            </BreadcrumbLink>
          </BreadcrumbItem>
          {product.category_data?.name && (
            <>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbLink href="#" onClick={(e) => e.preventDefault()}>
                  {product.category_data.name}
                </BreadcrumbLink>
              </BreadcrumbItem>
            </>
          )}
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{product.name}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Back */}
      <Button variant="ghost" className="w-fit gap-2" onClick={onBack}>
        <ArrowLeft className="h-4 w-4" />
        {t('common.backToList')}
      </Button>

      {/* Main layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left: Image */}
        <Card className="overflow-hidden py-0 gap-0">
          <CardContent className="p-0">
            <div className="aspect-square flex items-center justify-center bg-muted">
              {imageUrl ? (
                <img src={imageUrl} alt={product.name} className="w-full h-full object-contain" />
              ) : (
                <Package className="h-24 w-24 text-muted-foreground/30" strokeWidth={1} />
              )}
            </div>
            {/* Thumbnails — only real images */}
            {product.images && product.images.length > 1 && (
              <div className="flex gap-2 p-4">
                {product.images.map((img, i) => (
                  <div key={img.id} className={`flex h-16 w-16 items-center justify-center rounded-lg border-2 overflow-hidden ${i === 0 ? 'border-primary' : 'border-transparent'} bg-muted`}>
                    {img.image_url ? (
                      <img src={img.image_url} alt="" className="h-full w-full object-cover" />
                    ) : (
                      <Package className="h-6 w-6 text-muted-foreground/40" />
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Right: Info */}
        <div className="flex flex-col gap-4">
          {/* Title + Status */}
          <div>
            <h1 className="text-xl font-bold tracking-tight">{product.name}</h1>
            {product.sku && (
              <p className="text-sm text-muted-foreground font-mono mt-1">{product.sku}</p>
            )}
          </div>

          {/* Badges */}
          <div className="flex flex-wrap items-center gap-2">
            {product.stock_status && (
              <StatusBadge label={t(`productStatuses.${stockStatusKey}`)} variant={getStockVariant(product.stock_status)} />
            )}
            <Badge variant="secondary" className="text-xs">{product.domain_type_name}</Badge>
            {product.category_data?.name && (
              <Badge variant="outline" className="text-xs">{product.category_data.name}</Badge>
            )}
          </div>

          {/* Description */}
          {product.description && (
            <p className="text-sm text-muted-foreground leading-relaxed">{product.description}</p>
          )}

          <Separator />

          {/* Key attributes */}
          <Table>
            <TableBody>
              {attributes.map((attr) => (
                <TableRow key={attr.label}>
                  <TableCell className="text-muted-foreground font-medium w-40">{attr.label}</TableCell>
                  <TableCell className="text-right">{attr.value}</TableCell>
                </TableRow>
              ))}
              {showPrices && product.base_price && parseFloat(product.base_price) > 0 && (
                <TableRow>
                  <TableCell className="text-muted-foreground font-medium">{t('productDetail.priceFCA')}</TableCell>
                  <TableCell className="text-right font-bold text-primary tabular-nums">
                    {formatCurrency(parseFloat(product.base_price))}
                    {product.currency_data?.code && ` ${product.currency_data.code}`}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

          <Separator />

          {/* Add to request (BUYER only) */}
          {canSendRequest && (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1">
                <Button variant="outline" size="icon" className="h-9 w-9" onClick={() => setQty(Math.max(1, qty - 1))}>
                  <Minus className="h-4 w-4" />
                </Button>
                <Input
                  type="number"
                  value={qty}
                  onChange={(e) => setQty(Math.max(1, Number(e.target.value) || 1))}
                  className="h-9 w-20 text-center tabular-nums"
                />
                <Button variant="outline" size="icon" className="h-9 w-9" onClick={() => setQty(qty + 1)}>
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
              <Button
                className="flex-1 gap-2"
                onClick={() => { addItem(product, qty); openCart(); }}
              >
                <ShoppingCart className="h-4 w-4" />
                {t('productDetail.addToRequest')}
              </Button>
            </div>
          )}

          {/* Equipment groups */}
          {product.equipment_groups && product.equipment_groups.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {product.equipment_groups.map(g => (
                <Badge key={g.id} variant="outline" className="text-xs">{g.name}</Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Bottom tabs */}
      {(specEntries.length > 0 || (product.documents && product.documents.length > 0)) && (
        <Tabs defaultValue="specifications">
          <TabsList>
            <TabsTrigger value="specifications">
              {t('productDetail.specifications')} {specEntries.length > 0 && `(${specEntries.length})`}
            </TabsTrigger>
            {product.documents && product.documents.length > 0 && (
              <TabsTrigger value="documents">
                {t('productDetail.documents')} ({product.documents.length})
              </TabsTrigger>
            )}
          </TabsList>

          <TabsContent value="specifications">
            <Card className="py-0 gap-0">
              <CardContent className="p-0">
                {specEntries.length > 0 ? (
                  <Table>
                    <TableBody>
                      {specEntries.map(([key, value]) => (
                        <TableRow key={key}>
                          <TableCell className="font-medium text-muted-foreground w-48">{key}</TableCell>
                          <TableCell>{String(value)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
                    {t('productDetail.noSpecifications')}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {product.documents && product.documents.length > 0 && (
            <TabsContent value="documents">
              <Card>
                <CardContent className="space-y-2">
                  {product.documents.map((doc) => (
                    <a
                      key={doc.id}
                      href={doc.file_url || doc.file || '#'}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-3 rounded-lg border p-3 hover:bg-accent transition-colors"
                    >
                      <Package className="h-4 w-4 text-primary shrink-0" />
                      <span className="text-sm font-medium">{doc.name || t('productDetail.document')}</span>
                    </a>
                  ))}
                </CardContent>
              </Card>
            </TabsContent>
          )}
        </Tabs>
      )}
    </div>
  );
}
