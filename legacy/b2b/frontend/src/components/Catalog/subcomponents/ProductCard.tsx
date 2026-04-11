import React from 'react';
import { useTranslation } from 'react-i18next';
import { Product } from '../../../api/catalogApi';
import { Package, Lock, ShoppingCart, Check, FileText, ShieldCheck, Star, Award } from 'lucide-react';
import { useCartStore } from '../../../store/cartStore';
import { useUserStore } from '../../../store/userStore';
import { Button } from '@/components/ui/button';
import { clsx } from 'clsx';
import { getDomainVisual } from '../../../config/domainConfig';

// TODO: Fetch manufacturer verification data from API
// For now, use empty object — badge display should degrade gracefully
const verifiedManufacturers: Record<string, { verified: boolean; iso: boolean; trustScore: number }> = {};

interface ProductCardProps {
    product: Product;
    onClick: (product: Product) => void;
    canSeePrices: boolean;
}

const stockConfig = {
    IN_STOCK:  { color: 'text-success bg-success/10 border-success/20', dotColor: 'bg-success', labelKey: 'catalog.stock.inStock' },
    EXPECTED:  { color: 'text-primary bg-primary/10 border-primary/20', dotColor: 'bg-primary', labelKey: 'catalog.stock.expected' },
    ON_ORDER:  { color: 'text-warning bg-warning/10 border-warning/20', dotColor: 'bg-warning', labelKey: 'catalog.stock.onOrder' },
};

export const ProductCard: React.FC<ProductCardProps> = ({ product, onClick, canSeePrices }) => {
    const { t } = useTranslation();
    const { addItem, items, openCart } = useCartStore();
    const activeStatus = useUserStore((s) => s.activeStatus);

    const stock = stockConfig[product.stock_status as keyof typeof stockConfig] ?? stockConfig.ON_ORDER;
    const domainVisual = getDomainVisual(product.domain_type_code ?? 'GENERAL_GOODS');
    const inCart = items.some(i => Number(i.product.id) === Number(product.id));
    const mfgName = product.manufacturer_data?.name ?? '';
    const mfgInfo = verifiedManufacturers[mfgName];
    const isBuyer = activeStatus === 'BUYER';

    const handleAddToCart = (e: React.MouseEvent) => {
        e.stopPropagation();
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        addItem(product as any);
        openCart();
    };

    return (
        <article
            onClick={() => onClick(product)}
            className="group bg-card border border-border rounded-xl overflow-hidden cursor-pointer flex flex-col h-full transition-all duration-200 hover:border-primary/60 hover:shadow-lg hover:shadow-primary/5"
        >
            {/* Image */}
            <div className="relative aspect-[4/3] bg-muted overflow-hidden flex items-center justify-center">
                {product.main_image_url ? (
                    <img
                        src={product.main_image_url}
                        alt={product.name}
                        className="w-full h-full object-contain group-hover:scale-105 transition-transform duration-300"
                    />
                ) : (
                    <Package className="w-12 h-12 text-muted-foreground/30" aria-hidden="true" />
                )}

                {/* Domain badge */}
                <span className={clsx('absolute top-2 left-2 px-2 py-0.5 rounded-md text-xs font-semibold border', domainVisual.badgeClass)}>
                    {t(domainVisual.shortLabelKey)}
                </span>

                {/* Stock badge */}
                <span className={clsx('absolute top-2 right-2 flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium border', stock.color)}>
                    <span className={clsx('w-1.5 h-1.5 rounded-full', stock.dotColor)} aria-hidden="true" />
                    {t(stock.labelKey)}
                </span>
            </div>

            {/* Body */}
            <div className="p-4 flex flex-col flex-1">
                {/* SKU + GOST row */}
                <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-muted-foreground font-medium tabular-nums">
                        {product.sku ?? '—'}
                    </span>
                    {product.gost_drawing && (
                        <span className="flex items-center gap-1 text-xs text-muted-foreground">
                            <FileText className="w-3 h-3" aria-hidden="true" />
                            {product.gost_drawing}
                        </span>
                    )}
                </div>

                {/* Name */}
                <h3 className="text-sm font-semibold text-foreground leading-snug line-clamp-2 mb-2 group-hover:text-primary transition-colors">
                    {product.name}
                </h3>

                {/* Manufacturer + Verified badges */}
                {product.manufacturer_data?.name && (
                    <div className="mb-3 space-y-1.5">
                        <div className="flex items-center gap-1.5">
                            {mfgInfo?.verified && (
                                <ShieldCheck className="w-3.5 h-3.5 text-primary shrink-0" />
                            )}
                            <p className="text-xs text-muted-foreground truncate">
                                {product.manufacturer_data.name}
                            </p>
                        </div>
                        {mfgInfo && (
                            <div className="flex items-center gap-1.5 flex-wrap">
                                {mfgInfo.verified && (
                                    <span className="inline-flex items-center gap-1 text-xs font-medium text-accent-foreground bg-accent px-1.5 py-0.5 rounded">
                                        <ShieldCheck className="w-2.5 h-2.5" /> {t('catalog.card.verified')}
                                    </span>
                                )}
                                {mfgInfo.iso && (
                                    <span className="inline-flex items-center gap-1 text-xs font-medium text-success bg-success/10 px-1.5 py-0.5 rounded">
                                        <Award className="w-2.5 h-2.5" /> ISO 9001
                                    </span>
                                )}
                                <span className="inline-flex items-center gap-1 text-xs font-medium text-warning bg-warning/10 px-1.5 py-0.5 rounded">
                                    <Star className="w-2.5 h-2.5" /> {mfgInfo.trustScore}
                                </span>
                            </div>
                        )}
                    </div>
                )}

                {/* Price + Cart */}
                <div className="mt-auto pt-3 border-t border-border flex items-center justify-between gap-2">
                    <div className="min-w-0">
                        {isBuyer ? (
                            <>
                                <p className="text-xs text-muted-foreground font-medium mb-0.5">{t('catalog.card.priceOnRequest')}</p>
                                <Button
                                    variant="link"
                                    size="sm"
                                    onClick={(e) => { e.stopPropagation(); handleAddToCart(e); }}
                                    className="h-auto p-0 text-xs font-semibold"
                                >
                                    {t('catalog.card.requestQuote')}
                                </Button>
                            </>
                        ) : (
                            <>
                                <p className="text-xs text-muted-foreground mb-0.5">{t('catalog.productDetail.priceFCA')}</p>
                                {canSeePrices ? (
                                    <p className="text-base font-bold text-foreground tabular-nums">
                                        {Number(product.base_price).toLocaleString('ru-RU', { minimumFractionDigits: 0 })}
                                        <span className="text-xs font-semibold text-muted-foreground ml-1">
                                            {product.currency_data?.code ?? 'USD'}
                                        </span>
                                    </p>
                                ) : (
                                    <div className="flex items-center gap-1.5 text-warning">
                                        <Lock className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                                        <span className="text-xs font-medium">{t('catalog.productDetail.priceRestricted')}</span>
                                    </div>
                                )}
                            </>
                        )}
                    </div>

                    {!isBuyer && (
                        <Button
                            variant={inCart ? 'default' : 'outline'}
                            size="icon"
                            onClick={handleAddToCart}
                            aria-label={inCart ? t('cart.addedToCart') : t('cart.addToCart')}
                            className={clsx(
                                'shrink-0 w-9 h-9 rounded-lg',
                                inCart && 'bg-success border-success text-success-foreground hover:bg-success/90'
                            )}
                        >
                            {inCart ? <Check className="w-4 h-4" /> : <ShoppingCart className="w-4 h-4" />}
                        </Button>
                    )}
                </div>
            </div>
        </article>
    );
};
