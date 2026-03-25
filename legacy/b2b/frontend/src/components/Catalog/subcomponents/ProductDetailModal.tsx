import React from 'react';
import { useTranslation } from 'react-i18next';
import { Product } from '../../../api/catalogApi';
import { ShoppingCart, Download, Info, Package, Lock as LockIcon, MessageSquare, ShieldCheck, Star, Award, FileText as FileTextIcon } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
} from '@/components/ui/dialog';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';

// TODO: Fetch manufacturer verification data from API
// const verifiedManufacturers: Record<string, { verified: boolean; iso: boolean; trustScore: number }> = {};
const verifiedManufacturers: Record<string, { verified: boolean; iso: boolean; trustScore: number }> = {};

// TODO: Fetch technical documents from API or product.documents
const demoDocuments: { name: string; size: string }[] = [];

interface ProductDetailModalProps {
    product: Product | null;
    onClose: () => void;
    canSeePrices: boolean;
}

export const ProductDetailModal: React.FC<ProductDetailModalProps> = ({ product, onClose, canSeePrices }) => {
    const { t } = useTranslation();

    if (!product) return null;

    const stockStatusKey = product.stock_status || 'IN_STOCK';
    const stockVariant = stockStatusKey === 'IN_STOCK' ? 'default'
        : stockStatusKey === 'LOW_STOCK' ? 'secondary'
        : 'outline';

    const mfgName = product.manufacturer_data?.name ?? '';
    const mfgInfo = verifiedManufacturers[mfgName];

    const basePrice = Number(product.base_price) || 0;
    const currencyCode = product.currency_data?.code || 'USD';
    const formatPrice = (price: number) =>
        price.toLocaleString('en-US', { minimumFractionDigits: 2 });

    const volumeTiers = [
        { range: '1–10', price: basePrice, discount: null },
        { range: '10–50', price: basePrice * 0.95, discount: '−5%' },
        { range: '50+', price: basePrice * 0.88, discount: '−12%' },
    ];

    return (
        <Dialog open={!!product} onOpenChange={(open) => { if (!open) onClose(); }}>
            <DialogContent className="flex max-h-[85vh] flex-col overflow-hidden p-0 sm:max-w-4xl lg:flex-row" showCloseButton>
                {/* Media Section */}
                <div className="flex items-center justify-center border-b border-border bg-muted p-6 lg:w-2/5 lg:border-b-0 lg:border-r">
                    {product.main_image_url ? (
                        <img
                            src={product.main_image_url}
                            alt={product.name}
                            className="max-h-full max-w-full object-contain"
                        />
                    ) : (
                        <div className="flex flex-col items-center gap-3 text-muted-foreground">
                            <Package className="size-16" aria-hidden="true" />
                            <span className="text-xs">{t('catalog.productDetail.noImage')}</span>
                        </div>
                    )}
                </div>

                {/* Content Section */}
                <div className="flex min-h-0 flex-1 flex-col lg:w-3/5">
                    {/* Header */}
                    <DialogHeader className="p-6 pb-4">
                        <div className="mb-3 flex flex-wrap items-center gap-2">
                            <Badge>
                                {product.domain_type_name || t('domains.GENERAL_GOODS')}
                            </Badge>
                            <Badge variant={stockVariant as 'default' | 'secondary' | 'outline'}>
                                {t(`catalog.stock.${stockStatusKey}`)}
                            </Badge>
                        </div>
                        <DialogTitle className="text-lg leading-tight">
                            {product.name}
                        </DialogTitle>
                        <DialogDescription className="flex items-center gap-4 text-xs">
                            <span>{t('catalog.table.sku')}: {product.sku || '\u2014'}</span>
                            {product.gost_drawing && (
                                <span>GOST: {product.gost_drawing}</span>
                            )}
                        </DialogDescription>
                        {mfgInfo && (
                            <div className="mt-2 flex flex-wrap items-center gap-2">
                                {mfgInfo.verified && (
                                    <Badge variant="outline" className="gap-1 border-primary/20 bg-primary/10 text-primary">
                                        <ShieldCheck className="size-3" aria-hidden="true" />
                                        Verified Manufacturer
                                    </Badge>
                                )}
                                {mfgInfo.iso && (
                                    <Badge variant="outline" className="gap-1 border-green-200 bg-green-50 text-green-700 dark:border-green-500/30 dark:bg-green-500/10 dark:text-green-400">
                                        <Award className="size-3" aria-hidden="true" />
                                        ISO 9001
                                    </Badge>
                                )}
                                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                                    <Star className="size-3 fill-amber-400 text-amber-400" aria-hidden="true" />
                                    {mfgInfo.trustScore}
                                </span>
                            </div>
                        )}
                    </DialogHeader>

                    {/* Tabs */}
                    <Tabs defaultValue="info" className="flex flex-1 flex-col px-6 min-h-0">
                        <TabsList variant="line">
                            <TabsTrigger value="info">
                                {t('catalog.productDetail.description')}
                            </TabsTrigger>
                            <TabsTrigger value="pricing">
                                Цены и наличие
                            </TabsTrigger>
                            <TabsTrigger value="specs">
                                {t('catalog.productDetail.specifications')}
                            </TabsTrigger>
                            <TabsTrigger value="docs">
                                Документация
                            </TabsTrigger>
                        </TabsList>

                        <ScrollArea className="flex-1 min-h-0">
                            <TabsContent value="info" className="p-4">
                                <div className="space-y-5">
                                    <div className="grid grid-cols-2 gap-x-4 gap-y-5">
                                        <div className="border-l-2 border-border pl-3">
                                            <p className="mb-1 text-xs text-muted-foreground">{t('catalog.table.manufacturer')}</p>
                                            <p className="text-sm font-semibold">{product.manufacturer_data?.name || '\u2014'}</p>
                                        </div>
                                        <div className="border-l-2 border-border pl-3">
                                            <p className="mb-1 text-xs text-muted-foreground">{t('catalog.table.origin')}</p>
                                            <p className="text-sm font-semibold">{product.manufacturer_data?.country || '\u2014'}</p>
                                        </div>
                                        <div className="border-l-2 border-border pl-3">
                                            <p className="mb-1 text-xs text-muted-foreground">{t('catalog.filters.category')}</p>
                                            <p className="text-sm font-semibold">{product.category_data?.name || '\u2014'}</p>
                                        </div>
                                        <div className="border-l-2 border-border pl-3">
                                            <p className="mb-1 text-xs text-muted-foreground">{t('catalog.table.unit')}</p>
                                            <p className="text-sm font-semibold">
                                                {product.uom_data?.name || '\u0448\u0442'} ({product.uom_data?.code || 'pcs'})
                                            </p>
                                        </div>
                                    </div>

                                    <Separator />

                                    <div>
                                        <p className="mb-2 text-xs text-muted-foreground">{t('catalog.productDetail.description')}</p>
                                        <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">
                                            {product.description || t('common.noData')}
                                        </p>
                                    </div>
                                </div>
                            </TabsContent>

                            <TabsContent value="pricing" className="p-4">
                                <div className="space-y-5">
                                    {/* MOQ */}
                                    <div className="flex items-center gap-3">
                                        <Package className="size-4 text-primary" aria-hidden="true" />
                                        <span className="text-sm font-medium">Минимальный заказ: 1 шт</span>
                                    </div>

                                    {/* Stock availability */}
                                    <div className="flex flex-wrap gap-2">
                                        <Badge className="gap-1 border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-400" variant="outline">
                                            В наличии: 45 шт
                                        </Badge>
                                        <Badge className="gap-1 border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400" variant="outline">
                                            Под заказ: 14-21 дн.
                                        </Badge>
                                    </div>

                                    <Separator />

                                    {/* Volume pricing table */}
                                    <div>
                                        <p className="mb-3 text-sm font-semibold">Оптовые цены</p>
                                        <div className="rounded-lg border border-border overflow-hidden">
                                            <table className="w-full text-sm">
                                                <thead>
                                                    <tr className="bg-muted text-muted-foreground">
                                                        <th className="px-4 py-2 text-left font-medium">Кол-во</th>
                                                        <th className="px-4 py-2 text-right font-medium">Цена / шт</th>
                                                        <th className="px-4 py-2 text-right font-medium">Скидка</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {volumeTiers.map((tier, idx) => (
                                                        <tr key={idx} className="border-t border-border">
                                                            <td className="px-4 py-2">{tier.range}</td>
                                                            <td className="px-4 py-2 text-right tabular-nums font-medium">
                                                                {canSeePrices ? (
                                                                    <>
                                                                        {formatPrice(tier.price)}{' '}
                                                                        <span className="text-xs text-muted-foreground">{currencyCode}</span>
                                                                    </>
                                                                ) : (
                                                                    <span className="flex items-center justify-end gap-1 text-amber-600">
                                                                        <LockIcon className="size-3" aria-hidden="true" />
                                                                        Скрыто
                                                                    </span>
                                                                )}
                                                            </td>
                                                            <td className="px-4 py-2 text-right text-muted-foreground">
                                                                {tier.discount || '—'}
                                                            </td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    </div>
                                </div>
                            </TabsContent>

                            <TabsContent value="docs" className="p-4">
                                <div className="space-y-2">
                                    {demoDocuments.map((doc, idx) => (
                                        <div
                                            key={idx}
                                            className="flex items-center justify-between rounded-lg border border-border px-4 py-3"
                                        >
                                            <div className="flex items-center gap-3">
                                                <FileTextIcon className="size-4 text-primary" aria-hidden="true" />
                                                <div>
                                                    <p className="text-sm font-medium">{doc.name}</p>
                                                    <p className="text-xs text-muted-foreground">{doc.size}</p>
                                                </div>
                                            </div>
                                            <Button variant="ghost" size="icon" aria-label={`Скачать ${doc.name}`}>
                                                <Download className="size-4" />
                                            </Button>
                                        </div>
                                    ))}
                                </div>
                            </TabsContent>

                            <TabsContent value="specs" className="p-4">
                                <div className="space-y-4">
                                    {product.specifications?.tech_specs ? (
                                        <div className="rounded-lg border border-border bg-muted p-4">
                                            <div className="mb-3 flex items-center gap-2">
                                                <Info className="size-3.5 text-primary" aria-hidden="true" />
                                                <p className="text-sm font-semibold">{t('catalog.productDetail.specifications')}</p>
                                            </div>
                                            <p className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground">
                                                {product.specifications.tech_specs}
                                            </p>
                                        </div>
                                    ) : (
                                        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted py-10 text-muted-foreground">
                                            <Info className="mb-2 size-6 opacity-50" aria-hidden="true" />
                                            <p className="text-sm">{t('catalog.productDetail.noSpecifications')}</p>
                                        </div>
                                    )}
                                </div>
                            </TabsContent>
                        </ScrollArea>
                    </Tabs>

                    {/* Footer / CTA */}
                    <Separator />
                    <div className="flex items-center gap-4 bg-muted p-5">
                        <div className="flex-1">
                            <p className="mb-0.5 text-xs text-muted-foreground">{t('quote.basePrice')}</p>
                            {canSeePrices ? (
                                <p className="text-lg font-bold tabular-nums">
                                    {Number(product.base_price).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                                    <span className="ml-1 text-xs font-medium text-muted-foreground">
                                        {product.currency_data?.code || 'USD'}
                                    </span>
                                </p>
                            ) : (
                                <div className="flex items-center gap-2 text-amber-600">
                                    <LockIcon className="size-3.5" aria-hidden="true" />
                                    <span className="text-sm">{t('catalog.priceHidden')}</span>
                                </div>
                            )}
                        </div>

                        <div className="flex gap-2">
                            <Button variant="outline">
                                <MessageSquare className="size-4" />
                                Консультация эксперта
                            </Button>
                            {product.main_document_url && (
                                <Button
                                    variant="outline"
                                    size="icon"
                                    asChild
                                >
                                    <a
                                        href={product.main_document_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        aria-label={t('catalog.productDetail.documents')}
                                    >
                                        <Download className="size-4" />
                                    </a>
                                </Button>
                            )}
                            {canSeePrices ? (
                                <Button>
                                    <ShoppingCart className="size-4" />
                                    {t('catalog.productDetail.addToRequest')}
                                </Button>
                            ) : (
                                <Button asChild>
                                    <Link to="/register">
                                        {t('kyc.banner.action')}
                                    </Link>
                                </Button>
                            )}
                        </div>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
};
