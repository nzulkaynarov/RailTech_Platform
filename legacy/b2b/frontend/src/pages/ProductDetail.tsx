import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft,
  Bookmark,
  ShoppingCart,
  Minus,
  Plus,
  Package,
  Layers,
  ChevronRight,
  Loader2,
} from 'lucide-react';
import { useCartStore } from '@/store/cartStore';

import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableRow,
} from '@/components/ui/table';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

import {
  statusLabels,
  domainLabels,
  type Product,
} from '@/data/products';

// ─── Status & Domain Badges ─────────────────────────────────────────────

function StatusDot({ status }: { status: Product['status'] }) {
  const { t } = useTranslation();
  const dotColor: Record<Product['status'], string> = {
    in_stock: 'bg-success',
    to_order: 'bg-warning',
    sourcing: 'bg-primary',
    inactive: 'bg-destructive',
  };
  return (
    <div className="flex items-center gap-2">
      <span className={`h-2.5 w-2.5 rounded-full ${dotColor[status]}`} />
      <span className="text-sm font-medium">{t(statusLabels[status])}</span>
    </div>
  );
}

function DomainBadge({ domain }: { domain: Product['domain'] }) {
  const { t } = useTranslation();
  const colorMap: Record<Product['domain'], string> = {
    RAILWAY_MACHINERY: 'bg-primary/10 text-primary border-primary/20',
    GENERAL_GOODS: 'bg-muted text-foreground border-border',
    SERVICES: 'bg-accent text-accent-foreground border-border',
  };
  return (
    <Badge variant="outline" className={`text-xs font-medium ${colorMap[domain]}`}>
      {t(domainLabels[domain])}
    </Badge>
  );
}

// ─── Product Image Placeholder ──────────────────────────────────────────

function ProductImagePlaceholder({ product }: { product: Product }) {
  const bgColors: Record<Product['domain'], string> = {
    RAILWAY_MACHINERY: 'from-primary/10 to-muted',
    GENERAL_GOODS: 'from-muted to-muted',
    SERVICES: 'from-accent to-muted',
  };
  const iconColors: Record<Product['domain'], string> = {
    RAILWAY_MACHINERY: 'text-primary/30',
    GENERAL_GOODS: 'text-muted-foreground/30',
    SERVICES: 'text-muted-foreground/30',
  };

  return (
    <div className={`flex aspect-square items-center justify-center rounded-xl bg-gradient-to-br ${bgColors[product.domain]}`}>
      <Package className={`h-24 w-24 ${iconColors[product.domain]}`} strokeWidth={1} />
    </div>
  );
}

// ─── Similar Product Card ───────────────────────────────────────────────

function SimilarProductCard({ product, onNavigate }: { product: Product; onNavigate: (id: string) => void }) {
  return (
    <Card
      className="cursor-pointer py-3 gap-2 transition-shadow hover:shadow-md"
      onClick={() => onNavigate(product.id)}
    >
      <CardContent className="px-3">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-lg bg-muted">
            <Package className="h-6 w-6 text-muted-foreground" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{product.name}</p>
            <p className="text-xs text-muted-foreground">{product.article}</p>
          </div>
          <ChevronRight className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────

interface ProductDetailProps {
  productId: string;
  onBack: () => void;
  onNavigate: (productId: string) => void;
}

export function ProductDetail({ productId, onBack, onNavigate }: ProductDetailProps) {
  const { t } = useTranslation();
  const { addItem, openCart } = useCartStore();
  const [apiProduct, setApiProduct] = useState<Record<string, unknown> | null>(null);
  const [apiLoading, setApiLoading] = useState(true);
  const [apiError, setApiError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setApiLoading(true);
    setApiError(null);
    import('@/api/catalogApi').then(({ catalogApi }) =>
      catalogApi.getProduct(productId)
    ).then((data) => {
      if (!cancelled) setApiProduct(data as unknown as Record<string, unknown>);
    }).catch((err) => {
      if (!cancelled) setApiError(err instanceof Error ? err.message : 'Error');
    }).finally(() => {
      if (!cancelled) setApiLoading(false);
    });
    return () => { cancelled = true; };
  }, [productId]);

  // Map API product to legacy Product type for compatibility
  const product: Product | undefined = apiProduct ? {
    id: String(apiProduct.id ?? productId),
    name: String(apiProduct.name ?? ''),
    article: String(apiProduct.sku ?? ''),
    gost: String(apiProduct.gost_drawing ?? ''),
    uom: String((apiProduct.uom_data as Record<string, unknown>)?.name ?? ''),
    quantity: 0,
    domain: (apiProduct.domain_type_name ?? 'GENERAL_GOODS') as Product['domain'],
    category: String((apiProduct.category_data as Record<string, unknown>)?.name ?? ''),
    status: 'in_stock' as const,
    manufacturer: String((apiProduct.manufacturer_data as Record<string, unknown>)?.name ?? ''),
    addedDate: String(apiProduct.created_at ?? ''),
    ownerCompanyId: '',
    partnerVisible: true,
    description: String(apiProduct.description ?? ''),
    specifications: (apiProduct.specifications ?? {}) as Record<string, string>,
    images: ((apiProduct.images as Array<Record<string, string>>) ?? []).map(i => i.image_url || i.image || ''),
    basePriceFCA: 0,
  } : undefined;

  const [qty, setQty] = useState(product?.packageQuantity ?? 10);
  const [saved, setSaved] = useState(false);

  if (apiLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (apiError || !product) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3">
        <p className="text-muted-foreground">{apiError || t('catalog.productNotFound')}</p>
        <Button variant="outline" onClick={onBack}>{t('common.back')}</Button>
      </div>
    );
  }

  const similarProducts: Product[] = [];

  const specs = product.specifications ?? {};
  const specEntries = Object.entries(specs);

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
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink href="#" onClick={(e) => e.preventDefault()}>
              {product.category}
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{product.name}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      {/* Back button */}
      <Button variant="ghost" className="w-fit gap-2" onClick={onBack}>
        <ArrowLeft className="h-4 w-4" />
        {t('common.backToList')}
      </Button>

      {/* Main card — FEROX-inspired layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left: Image */}
        <Card className="overflow-hidden py-0 gap-0">
          <CardContent className="p-6">
            <ProductImagePlaceholder product={product} />

            {/* Thumbnail row (placeholders) */}
            <div className="mt-4 flex gap-2">
              {[1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className={`flex h-16 w-16 items-center justify-center rounded-lg border-2 ${
                    i === 1 ? 'border-primary' : 'border-transparent'
                  } bg-muted`}
                >
                  <Package className="h-6 w-6 text-muted-foreground/40" />
                </div>
              ))}
            </div>

            {/* Matching tools */}
            {product.matchingTools && (
              <div className="mt-4">
                <Button variant="outline" className="w-full gap-2">
                  <Layers className="h-4 w-4" />
                  {t('productDetail.compatibleParts', { count: product.matchingTools })}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Right: Product info */}
        <div className="flex flex-col gap-4">
          {/* Title + Status */}
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col gap-2">
              <h1 className="text-xl font-bold tracking-tight">{product.name}</h1>
              <StatusDot status={product.status} />
            </div>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant={saved ? 'default' : 'outline'}
                  size="icon"
                  onClick={() => setSaved(!saved)}
                >
                  <Bookmark className={`h-4 w-4 ${saved ? 'fill-current' : ''}`} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{saved ? t('productDetail.inFavorites') : t('productDetail.saveToList')}</TooltipContent>
            </Tooltip>
          </div>

          {/* Description */}
          {product.description && (
            <p className="text-sm text-muted-foreground leading-relaxed">
              {product.description}
            </p>
          )}

          <Separator />

          {/* Key attributes table */}
          <Table>
            <TableBody>
              <TableRow>
                <TableCell className="text-muted-foreground font-medium w-40">{t('productDetail.article')}</TableCell>
                <TableCell className="text-right font-mono">{product.article}</TableCell>
              </TableRow>
              {product.materialId && (
                <TableRow>
                  <TableCell className="text-muted-foreground font-medium">Material ID</TableCell>
                  <TableCell className="text-right font-mono">{product.materialId}</TableCell>
                </TableRow>
              )}
              <TableRow>
                <TableCell className="text-muted-foreground font-medium">{t('productDetail.gostDrawing')}</TableCell>
                <TableCell className="text-right">{product.gost}</TableCell>
              </TableRow>
              {product.iso && (
                <TableRow>
                  <TableCell className="text-muted-foreground font-medium">ISO</TableCell>
                  <TableCell className="text-right">{product.iso}</TableCell>
                </TableRow>
              )}
              <TableRow>
                <TableCell className="text-muted-foreground font-medium">{t('productDetail.uom')}</TableCell>
                <TableCell className="text-right">{product.uom}</TableCell>
              </TableRow>
              {product.packageQuantity && (
                <TableRow>
                  <TableCell className="text-muted-foreground font-medium">{t('productDetail.packaging')}</TableCell>
                  <TableCell className="text-right">{product.packageQuantity} {product.uom}</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

          <Separator />

          {/* Quantity selector + Add to cart */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="icon"
                className="h-9 w-9"
                onClick={() => setQty(Math.max(1, qty - 1))}
              >
                <Minus className="h-4 w-4" />
              </Button>
              <Input
                type="number"
                value={qty}
                onChange={(e) => setQty(Math.max(1, Number(e.target.value) || 1))}
                className="h-9 w-20 text-center tabular-nums"
              />
              <Button
                variant="outline"
                size="icon"
                className="h-9 w-9"
                onClick={() => setQty(qty + 1)}
              >
                <Plus className="h-4 w-4" />
              </Button>
            </div>
            <Button
              className="flex-1 gap-2"
              onClick={() => {
                addItem(product as any, qty);
                openCart();
              }}
            >
              <ShoppingCart className="h-4 w-4" />
              {t('productDetail.addToRequest')}
            </Button>
          </div>

          {/* Domain + Category badges */}
          <div className="flex flex-wrap items-center gap-2">
            <DomainBadge domain={product.domain} />
            <Badge variant="outline" className="text-xs">{product.category}</Badge>
            <Badge variant="outline" className="text-xs">{product.manufacturer}</Badge>
          </div>
        </div>
      </div>

      {/* Bottom tabs: Specs / Similar / Data */}
      <Tabs defaultValue="specifications">
        <TabsList>
          <TabsTrigger value="specifications">{t('productDetail.specifications')}</TabsTrigger>
          <TabsTrigger value="similar">{t('productDetail.analogs')} ({similarProducts.length})</TabsTrigger>
          <TabsTrigger value="data">{t('productDetail.data')}</TabsTrigger>
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
                        <TableCell>{value}</TableCell>
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

        <TabsContent value="similar">
          {similarProducts.length > 0 ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {similarProducts.map((sp) => (
                <SimilarProductCard key={sp.id} product={sp} onNavigate={onNavigate} />
              ))}
            </div>
          ) : (
            <Card>
              <CardContent className="flex h-24 items-center justify-center text-sm text-muted-foreground">
                {t('productDetail.noAnalogs')}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="data">
          <Card className="py-0 gap-0">
            <CardContent className="p-0">
              <Table>
                <TableBody>
                  <TableRow>
                    <TableCell className="font-medium text-muted-foreground w-48">{t('productDetail.domain')}</TableCell>
                    <TableCell>{t(domainLabels[product.domain])}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="font-medium text-muted-foreground">{t('productDetail.category')}</TableCell>
                    <TableCell>{product.category}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="font-medium text-muted-foreground">{t('productDetail.manufacturer')}</TableCell>
                    <TableCell>{product.manufacturer}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="font-medium text-muted-foreground">{t('productDetail.dateAdded')}</TableCell>
                    <TableCell>{product.addedDate}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell className="font-medium text-muted-foreground">{t('productDetail.stockQuantity')}</TableCell>
                    <TableCell className="tabular-nums">{product.quantity} {product.uom}</TableCell>
                  </TableRow>
                  {product.prevQuantity !== undefined && (
                    <TableRow>
                      <TableCell className="font-medium text-muted-foreground">{t('productDetail.prevPeriod')}</TableCell>
                      <TableCell className="tabular-nums">{product.prevQuantity} {product.uom}</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
