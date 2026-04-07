import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Box, ExternalLink } from 'lucide-react';
import { useQuoteItems, useUpdateQuoteItem } from '../../hooks/useCRM';
import { useProducts } from '../../hooks/useCatalog';
import { Product, QuoteItem } from '../../api/crmApi';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/LoadingSkeleton';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';

export const SourcingGrid: React.FC = () => {
    const { t } = useTranslation();
    const { data: quoteItems = [], isLoading } = useQuoteItems({ product_is_null: true });
    const updateMutation = useUpdateQuoteItem();

    const [searchQuery, setSearchQuery] = useState('');
    const [selectedItemId, setSelectedItemId] = useState<number | null>(null);
    const [isProductPickerOpen, setIsProductPickerOpen] = useState(false);
    const [productSearch, setProductSearch] = useState('');
    const [domainFilter, setDomainFilter] = useState<string>('ALL');

    const { data: products = [] } = useProducts({ search: productSearch || undefined });

    const handleLinkProduct = async (itemId: number, productId: number) => {
        try {
            await updateMutation.mutateAsync({ id: itemId, data: { product: productId } });
            setIsProductPickerOpen(false);
            setSelectedItemId(null);
        } catch (error) {
            console.error('Error linking product:', error);
        }
    };

    if (isLoading) {
        return (
            <div className="flex h-full flex-col space-y-6 p-6 lg:p-8">
                <div className="space-y-2">
                    <Skeleton className="h-8 w-64" />
                    <Skeleton className="h-4 w-96" />
                </div>
                <div className="space-y-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <Skeleton key={i} className="h-16 w-full rounded-lg" />
                    ))}
                </div>
            </div>
        );
    }

    const filteredItems = quoteItems.filter(i => {
        const matchesSearch = i.imported_raw_name.toLowerCase().includes(searchQuery.toLowerCase());
        const isRailway = i.imported_raw_name.toLowerCase().match(/тепловоз|вагон|двигатель/);
        const matchesDomain = domainFilter === 'ALL' ||
                             (domainFilter === 'RAILWAY' && isRailway) ||
                             (domainFilter === 'GENERAL' && !isRailway);
        return matchesSearch && matchesDomain;
    });

    const selectedItem = (quoteItems as QuoteItem[]).find(i => i.id === selectedItemId);

    const domainLabels: Record<string, string> = {
        ALL: t('catalog.filters.allCategories'),
        RAILWAY: t('domains.RAILWAY_MACHINERY'),
        GENERAL: t('domains.GENERAL_GOODS'),
    };

    return (
        <div className="flex h-full flex-col p-4 lg:p-6">
            <Card className="flex flex-1 flex-col overflow-hidden">
                <CardHeader>
                    <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
                        <div>
                            <div className="mb-2 flex items-center gap-2">
                                <Badge variant="secondary">
                                    <Box className="size-3" aria-hidden="true" />
                                    {t('sourcing.title')}
                                </Badge>
                            </div>
                            <CardTitle className="text-2xl font-bold tracking-tight">
                                {t('sourcing.title')}
                            </CardTitle>
                            <CardDescription className="mt-1 max-w-xl">
                                {t('sourcing.uploadHint')}
                            </CardDescription>
                        </div>

                        <div className="flex flex-wrap items-center gap-3">
                            <div className="relative min-w-[280px]">
                                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                                <Input
                                    type="search"
                                    placeholder={t('sourcing.searchPlaceholder')}
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    aria-label={t('common.search')}
                                    className="pl-10"
                                />
                            </div>

                            <Select value={domainFilter} onValueChange={setDomainFilter}>
                                <SelectTrigger className="w-[180px]">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {(['ALL', 'RAILWAY', 'GENERAL'] as const).map((f) => (
                                        <SelectItem key={f} value={f}>
                                            {t(domainLabels[f])}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    </div>
                </CardHeader>

                <CardContent className="flex-1 overflow-x-auto">
                    {filteredItems.length === 0 ? (
                        <EmptyState
                            icon={<Box className="size-7 text-muted-foreground" />}
                            title={t('catalog.noResults')}
                            description={t('catalog.noResultsHint')}
                            className="py-16"
                        />
                    ) : (
                        <table className="w-full border-collapse">
                            <thead>
                                <tr className="border-b border-border bg-muted/50">
                                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                        {t('catalog.table.name')}
                                    </th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                        {t('catalog.table.unit')}
                                    </th>
                                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                        {t('dashboard.deals.title')}
                                    </th>
                                    <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                                        {t('sourcing.assignProduct')}
                                    </th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-border">
                                {filteredItems.map((item) => (
                                    <tr
                                        key={item.id}
                                        className="transition-colors hover:bg-muted/50"
                                    >
                                        <td className="px-4 py-3.5">
                                            <div className="mb-0.5 text-sm font-semibold">
                                                {item.imported_raw_name}
                                            </div>
                                            <div className="text-xs text-muted-foreground">
                                                {t('sourcing.noMatch')}
                                            </div>
                                        </td>
                                        <td className="px-4 py-3.5">
                                            <Badge variant="secondary" className="tabular-nums">
                                                {item.quantity}
                                            </Badge>
                                        </td>
                                        <td className="px-4 py-3.5">
                                            <span className="text-sm font-medium text-muted-foreground">
                                                #{item.quote}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3.5 text-center">
                                            <Button
                                                size="sm"
                                                onClick={() => {
                                                    setSelectedItemId(item.id);
                                                    setProductSearch(item.imported_raw_name);
                                                    setIsProductPickerOpen(true);
                                                }}
                                            >
                                                {t('sourcing.assignProduct')}
                                            </Button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </CardContent>
            </Card>

            {/* Product Picker Modal */}
            <Dialog open={isProductPickerOpen} onOpenChange={(open) => { if (!open) { setIsProductPickerOpen(false); setSelectedItemId(null); } }}>
                <DialogContent className="flex max-h-[80vh] flex-col sm:max-w-2xl">
                    <DialogHeader>
                        <DialogTitle>{t('sourcing.assignProduct')}</DialogTitle>
                        {selectedItem && (
                            <p className="text-sm text-muted-foreground">
                                {selectedItem.imported_raw_name}
                            </p>
                        )}
                    </DialogHeader>

                    <div className="bg-muted/50 p-4 -mx-6">
                        <div className="relative">
                            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                            <Input
                                type="search"
                                value={productSearch}
                                onChange={(e) => setProductSearch(e.target.value)}
                                className="pl-10"
                                placeholder={t('catalog.searchPlaceholder')}
                                aria-label={t('common.search')}
                            />
                        </div>
                    </div>

                    <ScrollArea className="flex-1 -mx-6 max-h-[400px]">
                        <div className="space-y-1.5 p-3">
                            {(products as Product[]).map(p => (
                                <Button
                                    key={p.id}
                                    variant="ghost"
                                    onClick={() => handleLinkProduct(selectedItemId!, p.id)}
                                    className={cn(
                                        "group flex w-full items-center justify-between rounded-lg border border-transparent p-3 h-auto text-left transition-all",
                                        "hover:border-primary/30 hover:bg-accent"
                                    )}
                                >
                                    <div className="flex items-center gap-3">
                                        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                                            <ExternalLink className="size-4" />
                                        </div>
                                        <div>
                                            <div className="text-sm font-semibold">{p.name}</div>
                                            <div className="text-xs text-muted-foreground">
                                                {p.sku} · {p.domain_type_name}
                                            </div>
                                        </div>
                                    </div>
                                    <div className="text-sm font-semibold tabular-nums text-muted-foreground group-hover:text-primary">
                                        {p.base_price}
                                    </div>
                                </Button>
                            ))}
                        </div>
                    </ScrollArea>

                    <div className="-mx-6 border-t px-6 pt-4 flex justify-end">
                        <Button
                            variant="ghost"
                            onClick={() => setIsProductPickerOpen(false)}
                        >
                            {t('common.cancel')}
                        </Button>
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    );
};
