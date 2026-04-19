import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ShoppingCart, Trash2, Plus, Minus, Package, ArrowRight, Loader2 } from 'lucide-react';
import { useCartStore } from '@/store/cartStore';
import { useFlowStore } from '@/store/flowStore';
import { crmApi } from '@/api/crmApi';
import { toast } from 'sonner';
import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle,
    SheetDescription,
    SheetFooter,
    SheetClose,
} from '@/components/ui/sheet';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';

interface CartDrawerProps {
    onNavigate?: (target: string) => void;
}

export const CartDrawer: React.FC<CartDrawerProps> = ({ onNavigate }) => {
    const { t } = useTranslation();
    const { isOpen, closeCart, items, removeItem, updateQuantity, clearCart } = useCartStore();
    const setActiveDeal = useFlowStore((s) => s.setActiveDealId);

    const totalItems = items.reduce((sum, i) => sum + i.quantity, 0);
    const [submitting, setSubmitting] = useState(false);

    const handleSubmit = async () => {
        if (items.length === 0) return;
        setSubmitting(true);
        try {
            const deal = await crmApi.createDeal({
                title: `${t('cart.requestFrom')} ${new Date().toLocaleDateString()}`,
                // Include SKU + quantity per line so the sales manager can match
                // items without re-asking the buyer. Note: QuoteItems are
                // created later by the sales manager from this spec — no
                // silent data loss because each line is preserved in notes.
                notes: items
                    .map((item) => `• ${item.product.sku ?? '—'} · ${item.product.name} · ×${item.quantity}`)
                    .join('\n'),
            });
            if (deal?.id) {
                toast.success(t('cart.requestCreated', { id: deal.id }));
                // Route the buyer into the newly created request so they can
                // see its status and track progress — avoids "submitted → nothing
                // happens" dead-end that confused the pilot tester.
                if (onNavigate) {
                    setActiveDeal(deal.id);
                    onNavigate('request-detail');
                }
            }
            clearCart();
            closeCart();
        } catch {
            toast.error(t('cart.requestError'));
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Sheet open={isOpen} onOpenChange={(open) => { if (!open) closeCart(); }}>
            <SheetContent side="right" className="flex flex-col sm:max-w-sm" showCloseButton={false}>
                <SheetHeader className="flex flex-row items-center justify-between space-y-0 px-5 py-4">
                    <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
                            <ShoppingCart className="h-4 w-4 text-primary" aria-hidden="true" />
                        </div>
                        <div>
                            <SheetTitle className="text-sm">
                                {t('cart.title')}
                            </SheetTitle>
                            <SheetDescription className="text-xs">
                                {t('cart.itemsCount', { count: totalItems })}
                            </SheetDescription>
                        </div>
                    </div>
                    <SheetClose asChild>
                        <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={t('common.close')}
                        >
                            <span className="sr-only">{t('common.close')}</span>
                            &times;
                        </Button>
                    </SheetClose>
                </SheetHeader>

                <Separator />

                <ScrollArea className="flex-1">
                    {items.length === 0 ? (
                        <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
                            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted">
                                <Package className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
                            </div>
                            <div>
                                <p className="text-sm font-semibold text-foreground">
                                    {t('cart.empty')}
                                </p>
                                <p className="mt-1 text-xs text-muted-foreground">
                                    {t('cart.emptyHint')}
                                </p>
                            </div>
                        </div>
                    ) : (
                        <ul className="divide-y divide-border">
                            {items.map(({ product, quantity }) => (
                                <li key={product.id} className="flex gap-3 p-4">
                                    {/* Thumbnail */}
                                    <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted">
                                        {(product.main_image_url || product.images?.[0]?.image_url) ? (
                                            <img
                                                src={product.main_image_url || product.images?.[0]?.image_url || ''}
                                                alt={product.name}
                                                className="h-full w-full object-contain"
                                            />
                                        ) : (
                                            <Package className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
                                        )}
                                    </div>

                                    {/* Details */}
                                    <div className="min-w-0 flex-1">
                                        <p className="mb-0.5 text-xs tabular-nums text-muted-foreground">
                                            {product.sku}
                                        </p>
                                        <p className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
                                            {product.name}
                                        </p>

                                        <div className="mt-2 flex items-center justify-between">
                                            {/* Quantity stepper */}
                                            <div className="flex items-center gap-0 overflow-hidden rounded-lg border">
                                                <Button
                                                    variant="ghost"
                                                    size="icon-xs"
                                                    onClick={() => updateQuantity(product.id, quantity - 1)}
                                                    aria-label={t('cart.decrease')}
                                                    className="rounded-none"
                                                >
                                                    <Minus className="h-3 w-3" />
                                                </Button>
                                                <span className="w-8 text-center text-sm font-semibold tabular-nums text-foreground">
                                                    {quantity}
                                                </span>
                                                <Button
                                                    variant="ghost"
                                                    size="icon-xs"
                                                    onClick={() => updateQuantity(product.id, quantity + 1)}
                                                    aria-label={t('cart.increase')}
                                                    className="rounded-none"
                                                >
                                                    <Plus className="h-3 w-3" />
                                                </Button>
                                            </div>

                                            <Button
                                                variant="ghost"
                                                size="icon-xs"
                                                onClick={() => removeItem(product.id)}
                                                aria-label={t('cart.remove')}
                                                className="text-muted-foreground hover:text-destructive"
                                            >
                                                <Trash2 className="h-4 w-4" />
                                            </Button>
                                        </div>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </ScrollArea>

                {items.length > 0 && (
                    <>
                        <Separator />
                        <SheetFooter className="px-5 py-4">
                            <Button
                                variant="ghost"
                                size="sm"
                                onClick={clearCart}
                                className="w-full text-xs text-muted-foreground hover:text-destructive"
                            >
                                {t('cart.clear')}
                            </Button>

                            <Button
                                size="lg"
                                className="w-full gap-2"
                                onClick={handleSubmit}
                                disabled={submitting || items.length === 0}
                            >
                                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                                {submitting ? t('common.loading') : t('cart.requestQuote')}
                            </Button>
                        </SheetFooter>
                    </>
                )}
            </SheetContent>
        </Sheet>
    );
};
