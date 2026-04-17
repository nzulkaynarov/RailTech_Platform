import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft, ShoppingCart, Minus, Plus, Package, FileText,
  Building2, Clock, Truck,
} from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { StatusBadge, getStockVariant } from '@/components/ui/StatusBadge';
import { Skeleton } from '@/components/ui/skeleton';

import { useProduct } from '@/hooks/useCatalog';
import { useCartStore } from '@/store/cartStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { useUserStore } from '@/store/userStore';
import { getDomainLabelKey } from '@/config/domainConfig';

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
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-32" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2 space-y-4">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-48 w-full" />
          </div>
          <Skeleton className="h-64 w-full" />
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
  const hasImages = product.images && product.images.length > 0;
  const specs = product.specifications ?? {};
  const specEntries = Object.entries(specs).filter(([, v]) => v != null && v !== '');
  const hasDocs = product.documents && product.documents.length > 0;
  const activeOffers = (product.offers ?? []).filter(o => o.is_active);

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
    <div className="flex flex-col gap-4">
      {/* Back */}
      <Button variant="ghost" className="w-fit gap-2 -ml-2" onClick={onBack}>
        <ArrowLeft className="h-4 w-4" />
        {t('common.backToList')}
      </Button>

      {/* Header — full width */}
      <Card>
        <CardContent className="p-5">
          <div className="flex gap-5">
            {hasImages && (
              <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-lg bg-muted overflow-hidden">
                {imageUrl ? (
                  <img src={imageUrl} alt={product.name} className="h-full w-full object-contain" loading="lazy" />
                ) : (
                  <Package className="h-8 w-8 text-muted-foreground/30" />
                )}
              </div>
            )}
            <div className="flex flex-col gap-1.5 min-w-0 flex-1">
              <h1 className="text-lg font-bold tracking-tight">{product.name}</h1>
              {product.sku && (
                <p className="text-sm text-muted-foreground font-mono">{product.sku}</p>
              )}
              <div className="flex flex-wrap items-center gap-1.5 mt-auto">
                {product.stock_status && (
                  <StatusBadge label={t(`productStatuses.${stockStatusKey}`)} variant={getStockVariant(product.stock_status)} />
                )}
                <Badge variant="secondary" className="text-xs">{product.domain_type_name}</Badge>
                {product.category_data?.name && (
                  <Badge variant="outline" className="text-xs">{product.category_data.name}</Badge>
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* ─── Left column (2/3) — product info ─── */}
        <div className="lg:col-span-2 flex flex-col gap-4">
          {/* Description */}
          {product.description && (
            <Card>
              <CardContent className="p-5">
                <h2 className="text-sm font-semibold mb-2">{t('productDetail.description')}</h2>
                <p className="text-sm text-muted-foreground leading-relaxed">{product.description}</p>
              </CardContent>
            </Card>
          )}

          {/* Attributes */}
          {attributes.length > 0 && (
            <Card>
              <CardContent className="p-5">
                <h2 className="text-sm font-semibold mb-3">{t('productDetail.characteristics')}</h2>
                <div className="space-y-2">
                  {attributes.map((attr) => (
                    <div key={attr.label} className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">{attr.label}</span>
                      <span className="text-sm font-medium">{attr.value}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Specifications */}
          {specEntries.length > 0 && (
            <Card>
              <CardContent className="p-5">
                <h2 className="text-sm font-semibold mb-3">{t('productDetail.specifications')} ({specEntries.length})</h2>
                <div className="space-y-2">
                  {specEntries.map(([key, value]) => (
                    <div key={key} className="flex items-center justify-between">
                      <span className="text-sm text-muted-foreground">{key}</span>
                      <span className="text-sm">{String(value)}</span>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Equipment groups */}
          {product.equipment_groups && product.equipment_groups.length > 0 && (
            <Card>
              <CardContent className="p-5">
                <h2 className="text-sm font-semibold mb-3">{t('productDetail.equipmentGroups')}</h2>
                <div className="flex flex-wrap gap-1.5">
                  {product.equipment_groups.map(g => (
                    <Badge key={g.id} variant="outline" className="text-xs">{g.name}</Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Documents */}
          {hasDocs && (
            <Card>
              <CardContent className="p-5">
                <h2 className="text-sm font-semibold mb-3">{t('productDetail.documents')} ({product.documents!.length})</h2>
                <div className="space-y-2">
                  {product.documents!.map((doc) => (
                    <a
                      key={doc.id}
                      href={doc.file_url || doc.file || '#'}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-3 rounded-lg border p-3 hover:bg-accent transition-colors"
                    >
                      <FileText className="h-4 w-4 text-primary shrink-0" />
                      <span className="text-sm font-medium">{doc.name || t('productDetail.document')}</span>
                    </a>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Images gallery */}
          {product.images && product.images.length > 1 && (
            <Card>
              <CardContent className="p-5">
                <h2 className="text-sm font-semibold mb-3">{t('productDetail.images')}</h2>
                <div className="flex gap-2 flex-wrap">
                  {product.images.map((img) => (
                    <div key={img.id} className="flex h-20 w-20 items-center justify-center rounded-lg border overflow-hidden bg-muted">
                      {img.image_url ? (
                        <img src={img.image_url} alt="" className="h-full w-full object-cover" loading="lazy" />
                      ) : (
                        <Package className="h-6 w-6 text-muted-foreground/40" />
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* ─── Right column (1/3) — actions & commercial ─── */}
        <div className="flex flex-col gap-4 lg:sticky lg:top-6 lg:self-start">
          {/* Price card (seller/manufacturer) */}
          {showPrices && product.base_price && parseFloat(product.base_price) > 0 && (
            <Card>
              <CardContent className="p-5 text-center">
                <p className="text-xs text-muted-foreground mb-1">{t('productDetail.priceFCA')}</p>
                <p className="text-2xl font-bold text-primary tabular-nums">
                  {formatCurrency(parseFloat(product.base_price))}
                </p>
                {product.currency_data?.code && (
                  <p className="text-xs text-muted-foreground mt-0.5">{product.currency_data.code}</p>
                )}
              </CardContent>
            </Card>
          )}

          {/* Add to request — BUYER */}
          {canSendRequest && (
            <Card>
              <CardContent className="p-4 space-y-3">
                <div className="flex items-center gap-1 justify-center">
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
                  className="w-full gap-2"
                  onClick={() => { addItem(product, qty); openCart(); }}
                >
                  <ShoppingCart className="h-4 w-4" />
                  {t('productDetail.addToRequest')}
                </Button>
              </CardContent>
            </Card>
          )}

          {/* Supplier Offers */}
          {activeOffers.length > 0 && (
            <Card>
              <CardContent className="p-5">
                <h2 className="text-sm font-semibold mb-3">
                  {t('productDetail.supplierOffers')} ({activeOffers.length})
                </h2>
                <div className="space-y-3">
                  {activeOffers.map((offer, i) => (
                    <div key={offer.id}>
                      {i > 0 && <Separator className="mb-3" />}
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Building2 className="h-4 w-4 text-muted-foreground shrink-0" />
                          <span className="text-sm font-medium truncate">{offer.supplier_data?.name}</span>
                        </div>
                        <p className="text-lg font-bold text-primary tabular-nums">
                          {formatCurrency(parseFloat(offer.base_price))}
                          {offer.currency_data?.code ? ` ${offer.currency_data.code}` : ''}
                        </p>
                        <div className="flex flex-col gap-1 text-xs text-muted-foreground">
                          {offer.delivery_basis_data?.name && (
                            <div className="flex items-center gap-1.5">
                              <Truck className="h-3 w-3 shrink-0" />
                              <span>{offer.delivery_basis_data.name}</span>
                            </div>
                          )}
                          {offer.delivery_lead_time && (
                            <div className="flex items-center gap-1.5">
                              <Clock className="h-3 w-3 shrink-0" />
                              <span>{offer.delivery_lead_time}</span>
                            </div>
                          )}
                          {offer.min_order_qty && offer.min_order_qty > 1 && (
                            <span>{t('productDetail.minOrder', { qty: offer.min_order_qty })}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
