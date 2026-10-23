import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  ArrowLeft, Package, FileText,
  Building2, Clock, Truck, Pencil, Send, EyeOff, Archive, ArchiveRestore,
} from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { getStockVariant } from '@/lib/statusVariants';
import { Skeleton } from '@/components/ui/skeleton';

import {
  useProduct, usePublishProduct, useUnpublishProduct, useArchiveProduct, useRestoreProduct,
} from '@/hooks/useCatalog';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { formatMoney } from '@/utils/decimal';
import { useAuthStore } from '@/store/authStore';
import { getDomainLabelKey } from '@/config/domainConfig';
import { deliveryBasisLabelKey, productStatusLabelKey, stockStatusLabelKey, uomLabelKey } from '@/lib/codes';
import { extractApiErrorCode, translateApiError } from '@/lib/apiError';
import { downloadFile } from '@/lib/download';

interface ProductDetailProps {
  productId: string;
  onBack: () => void;
  onNavigate: (productId: string) => void;
  /** Переход в страницу-редактор (`product-edit/{id}`); подключается роутингом R3. */
  onProductEdit?: (id: string) => void;
}

/** Тот же светофор статусов карточки, что в реестре и редакторе (R2/R3). */
const STATUS_BADGE_VARIANT: Record<string, 'success' | 'warning' | 'neutral'> = {
  PUBLISHED: 'success',
  DRAFT: 'warning',
  ARCHIVED: 'neutral',
};

export function ProductDetail({ productId, onBack, onProductEdit }: ProductDetailProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  // Карточка товара бэк-офиса: цена и предложения поставщиков видны всегда. Покупательская
  // ветка («Добавить в заявку», корзина) удалена в M1-ERP-02 волна 3 — витрина клиента в Cabinet.

  // Слой владельца (D15): статус и действия видит ТОЛЬКО компания-владелец карточки,
  // кнопки — по правам CompanyRole (скрыты без права, не disabled), как в редакторе.
  const viewerCompanyId = useAuthStore((s) => s.user?.company?.id);
  const canManage = useHasCompanyPermission('catalog.manage');
  const canPublish = useHasCompanyPermission('catalog.publish');
  const publishMut = usePublishProduct();
  const unpublishMut = useUnpublishProduct();
  const archiveMut = useArchiveProduct();
  const restoreMut = useRestoreProduct();

  const { data: product, isLoading, error, refetch } = useProduct(productId);

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
    // A failed fetch (network/server) is distinct from a genuinely missing product:
    // offer a retry on error, fall back to "not found" + back when there's no error.
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3">
        <Package className="h-12 w-12 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">{error ? t('common.loadError') : t('catalog.productNotFound')}</p>
        <div className="flex gap-2">
          {error && (
            <Button variant="outline" onClick={() => refetch()}>{t('common.retry')}</Button>
          )}
          <Button variant="ghost" onClick={onBack}>{t('common.back')}</Button>
        </div>
      </div>
    );
  }

  const imageUrl = product.main_image_url || product.images?.[0]?.image_url;
  const hasImages = product.images && product.images.length > 0;
  const specs = product.specifications ?? {};
  const specEntries = Object.entries(specs).filter(([, v]) => v != null && v !== '');
  const hasDocs = product.documents && product.documents.length > 0;
  const activeOffers = (product.offers ?? []).filter(o => o.is_active);

  // Подпись наличия берётся из общего словаря кодов: цепочка тернарников роняла всё,
  // кроме первых трёх кодов, в «Неактивен» — справочный OUT_OF_STOCK печатался как
  // отключённая карточка, хотя getStockVariant красил его в danger. Незнакомый код
  // даёт пустой ключ, и бейдж не рисуется вовсе — выдумывать ему подпись нельзя.
  const stockStatus = product.stock_status ?? '';
  const stockLabelKey = stockStatusLabelKey(stockStatus);

  // Заголовочная цена печатается ТОЛЬКО парой «число + валюта того же оффера».
  // `base_price` теперь null, когда активного оффера нет вовсе (раньше сервер отдавал
  // строку "0", и витрина показывала настоящий нулевой ценник), а cost-gate срезает
  // цену и валюту разом у того, кто карточкой не владеет. В обоих случаях правильный
  // ответ — не показывать ничего: ни «0», ни подписи, намекающей на незаполненность.
  const basePrice = product.base_price;
  const basePriceCurrency = product.base_price_currency;

  // ─── Владелец карточки: статус + действия жизненного цикла (D15) ───
  const isOwner = viewerCompanyId != null && product.owner_company_data?.id === viewerCompanyId;
  const statusCode = product.status_code ?? '';
  const statusLabelKey = productStatusLabelKey(statusCode);
  const actionPending = publishMut.isPending || unpublishMut.isPending
    || archiveMut.isPending || restoreMut.isPending;
  // Хуки инвалидируют списки (['products']); детальная карточка живёт под своим ключом.
  const actionSuccess = (message: string) => () => {
    queryClient.invalidateQueries({ queryKey: ['product', productId] });
    toast.success(message);
  };
  const actionError = (fallbackKey: string) => (err: unknown) =>
    toast.error(extractApiErrorCode(err) ? translateApiError(err) : t(fallbackKey));

  // «Опубликовать» — только DRAFT с достигнутой полнотой; при неполноте кнопка скрыта
  // (дозаполнение живёт в редакторе).
  const showPublish = canPublish && statusCode === 'DRAFT' && Boolean(product.completeness?.is_publishable);
  const showOwnerActions = isOwner && (canManage || canPublish);

  const attributes = [
    { label: t('productDetail.article'), value: product.sku },
    { label: t('productDetail.gostDrawing'), value: product.gost_drawing },
    { label: t('productDetail.uom'), value: product.uom_data ? (uomLabelKey(product.uom_data.code) ? t(uomLabelKey(product.uom_data.code)) : product.uom_data.name) : undefined },
    { label: t('productDetail.manufacturer'), value: product.brand_name },
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
          <div className="flex flex-wrap gap-5">
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
                {/* Статус публикации — только владельцу: чужие видят лишь PUBLISHED-карточки. */}
                {isOwner && statusLabelKey && (
                  <StatusBadge
                    label={t(statusLabelKey)}
                    variant={STATUS_BADGE_VARIANT[statusCode] ?? 'neutral'}
                  />
                )}
                {stockLabelKey && (
                  <StatusBadge label={t(stockLabelKey)} variant={getStockVariant(stockStatus)} />
                )}
                <Badge variant="secondary" className="text-xs">
                  {t(getDomainLabelKey(product.domain_type_code ?? ''), product.domain_type_name)}
                </Badge>
                {product.category_data?.name && (
                  <Badge variant="outline" className="text-xs">{product.category_data.name}</Badge>
                )}
              </div>
            </div>
            {/* Действия владельца — по правам, скрыты без права (у покупателя вид не меняется). */}
            {showOwnerActions && (
              <div className="flex flex-wrap items-start justify-end gap-1.5 shrink-0">
                {canManage && onProductEdit && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5"
                    onClick={() => onProductEdit(String(product.id))}
                  >
                    <Pencil className="size-4" aria-hidden="true" />
                    {t('productDetail.actions.edit')}
                  </Button>
                )}
                {showPublish && (
                  <Button
                    size="sm"
                    className="gap-1.5"
                    disabled={actionPending}
                    onClick={() =>
                      publishMut.mutate(product.id, {
                        onSuccess: actionSuccess(t('nomenclature.published', { name: product.name })),
                        onError: actionError('nomenclature.publishFailed'),
                      })
                    }
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
                    disabled={actionPending}
                    onClick={() =>
                      unpublishMut.mutate(product.id, {
                        onSuccess: actionSuccess(t('productDetail.actions.unpublished', { name: product.name })),
                        onError: actionError('productDetail.actions.failed'),
                      })
                    }
                  >
                    <EyeOff className="size-4" aria-hidden="true" />
                    {t('productDetail.actions.unpublish')}
                  </Button>
                )}
                {canManage && statusCode !== 'ARCHIVED' && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5"
                    disabled={actionPending}
                    onClick={() =>
                      archiveMut.mutate(product.id, {
                        onSuccess: actionSuccess(t('productDetail.actions.archived', { name: product.name })),
                        onError: actionError('productDetail.actions.failed'),
                      })
                    }
                  >
                    <Archive className="size-4" aria-hidden="true" />
                    {t('productDetail.actions.archive')}
                  </Button>
                )}
                {canManage && statusCode === 'ARCHIVED' && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5"
                    disabled={actionPending}
                    onClick={() =>
                      restoreMut.mutate(product.id, {
                        onSuccess: actionSuccess(t('productDetail.actions.restored', { name: product.name })),
                        onError: actionError('productDetail.actions.failed'),
                      })
                    }
                  >
                    <ArchiveRestore className="size-4" aria-hidden="true" />
                    {t('productDetail.actions.restore')}
                  </Button>
                )}
              </div>
            )}
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

          {/* Documents */}
          {hasDocs && (
            <Card>
              <CardContent className="p-5">
                <h2 className="text-sm font-semibold mb-3">{t('productDetail.documents')} ({product.documents!.length})</h2>
                <div className="space-y-2">
                  {product.documents!.map((doc) => {
                    const rowClass = 'flex w-full items-center gap-3 rounded-lg border p-3 text-left hover:bg-accent transition-colors';
                    const label = doc.name || t('productDetail.document');
                    // Загруженный файл приватный: открывается только через аутентифицированное скачивание (потоком), а не по адресу в хранилище.
                    if (doc.file) {
                      return (
                        <button
                          key={doc.id}
                          type="button"
                          className={rowClass}
                          onClick={() => {
                            downloadFile(`catalog/products/${product.id}/download-document/${doc.id}/`, label).catch((error) =>
                              toast.error(translateApiError(error)),
                            );
                          }}
                        >
                          <FileText className="h-4 w-4 text-primary shrink-0" />
                          <span className="text-sm font-medium">{label}</span>
                        </button>
                      );
                    }
                    return (
                      <a
                        key={doc.id}
                        href={doc.file_url || '#'}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={rowClass}
                      >
                        <FileText className="h-4 w-4 text-primary shrink-0" />
                        <span className="text-sm font-medium">{label}</span>
                      </a>
                    );
                  })}
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
          {/* Price card */}
          {basePrice && basePriceCurrency && Number(basePrice) > 0 && (
            <Card>
              <CardContent className="p-5 text-center">
                <p className="text-xs text-muted-foreground mb-1">{t('productDetail.priceFCA')}</p>
                <p className="text-2xl font-bold text-primary tabular-nums">
                  {formatMoney(basePrice, basePriceCurrency)}
                </p>

              </CardContent>
            </Card>
          )}

          {/* Supplier Offers — back-office cost internals; never leave ERP (the client sees
              only the published layer in Cabinet). */}
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
                          {/* Валюта берётся только у самого оффера. Дефолт `|| 'UZS'` подставлял
                              сумы офферу, у которого валюта не проставлена, — то же враньё, что
                              и жёсткое 'UZS' в шапке карточки (R1). Без валюты печатаем голое
                              число: неверный знак хуже отсутствующего. */}
                          {offer.currency_data?.code
                            ? formatMoney(offer.base_price, offer.currency_data.code)
                            : offer.base_price}
                        </p>
                        <div className="flex flex-col gap-1 text-xs text-muted-foreground">
                          {offer.delivery_basis_data && (
                            <div className="flex items-center gap-1.5">
                              <Truck className="h-3 w-3 shrink-0" />
                              <span>
                                {deliveryBasisLabelKey(offer.delivery_basis_data.code)
                                  ? t(deliveryBasisLabelKey(offer.delivery_basis_data.code))
                                  : offer.delivery_basis_data.name}
                              </span>
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
