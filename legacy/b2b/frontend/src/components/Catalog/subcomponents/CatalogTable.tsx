import React, { useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Product } from '../../../api/catalogApi';
import { Download, FileText, Lock as LockIcon, Package, ShoppingCart, X } from 'lucide-react';
import { StatusBadge, getStockVariant } from '@/components/ui/StatusBadge';
import { Checkbox } from '@/components/ui/checkbox';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useCartStore } from '@/store/cartStore';

interface CatalogTableProps {
    products: Product[];
    onProductClick: (product: Product) => void;
    canSeePrices: boolean;
}

export const CatalogTable: React.FC<CatalogTableProps> = ({ products, onProductClick, canSeePrices }) => {
    const { t } = useTranslation();
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
    const addBulk = useCartStore((s) => s.addBulk);

    const allSelected = products.length > 0 && selectedIds.size === products.length;
    const someSelected = selectedIds.size > 0 && selectedIds.size < products.length;

    const toggleAll = useCallback(() => {
        if (allSelected) {
            setSelectedIds(new Set());
        } else {
            setSelectedIds(new Set(products.map((p) => p.id)));
        }
    }, [allSelected, products]);

    const toggleOne = useCallback((id: number) => {
        setSelectedIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
            }
            return next;
        });
    }, []);

    const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

    const selectedProducts = useMemo(
        () => products.filter((p) => selectedIds.has(p.id)),
        [products, selectedIds],
    );

    const handleBulkAdd = useCallback(() => {
        addBulk(selectedProducts as unknown as Parameters<typeof addBulk>[0]);
        clearSelection();
    }, [addBulk, selectedProducts, clearSelection]);

    const handleExportCSV = useCallback(() => {
        const header = 'SKU,Name,Manufacturer,Price,UOM,Stock Status';
        const rows = selectedProducts.map((p) => {
            const sku = (p.sku || '').replace(/"/g, '""');
            const name = p.name.replace(/"/g, '""');
            const manufacturer = (p.brand_name || '').replace(/"/g, '""');
            const price = p.base_price ?? '';
            const uom = p.uom_data?.code || 'pcs';
            const stock = p.stock_status || 'IN_STOCK';
            return `"${sku}","${name}","${manufacturer}","${price}","${uom}","${stock}"`;
        });
        const csv = [header, ...rows].join('\n');
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'railtech_catalog_export.csv';
        link.click();
        URL.revokeObjectURL(url);
    }, [selectedProducts]);

    return (
        <div className="bg-background border border-border rounded-lg overflow-hidden shadow-sm">
            {selectedIds.size > 0 && (
                <div className="sticky top-0 z-20 flex items-center justify-between px-4 py-2.5 bg-accent border-b border-primary/20">
                    <span className="text-sm font-medium text-accent-foreground">
                        {t('catalog.table.selected', { count: selectedIds.size })}
                    </span>
                    <div className="flex items-center gap-2">
                        <Button
                            size="sm"
                            onClick={handleBulkAdd}
                        >
                            <ShoppingCart size={14} />
                            {t('catalog.table.addToRequest', { count: selectedIds.size })}
                        </Button>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={handleExportCSV}
                        >
                            <Download size={14} />
                            {t('catalog.table.exportCSV')}
                        </Button>
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={clearSelection}
                        >
                            <X size={14} />
                            {t('catalog.table.clearSelection')}
                        </Button>
                    </div>
                </div>
            )}
            <Table className="w-full text-left border-separate border-spacing-0">
                <TableHeader className="bg-muted dark:bg-background sticky top-0 z-10">
                    <TableRow className="text-xs uppercase font-semibold text-muted-foreground">
                        <TableHead className="py-2.5 px-3 border-b border-border w-10 text-center">
                            <Checkbox
                                checked={allSelected ? true : someSelected ? 'indeterminate' : false}
                                onCheckedChange={toggleAll}
                                aria-label="Select all"
                            />
                        </TableHead>
                        <TableHead className="py-2.5 px-3 border-b border-border w-10 text-center">#</TableHead>
                        <TableHead className="py-2.5 px-3 border-b border-border min-w-[280px]">{t('catalog.table.name')}</TableHead>
                        <TableHead className="py-2.5 px-3 border-b border-border w-44">{t('catalog.table.sku')}</TableHead>
                        <TableHead className="py-2.5 px-3 border-b border-border w-36">{t('catalog.table.manufacturer')}</TableHead>
                        <TableHead className="py-2.5 px-3 border-b border-border w-16 text-center">{t('catalog.table.unit')}</TableHead>
                        <TableHead className="py-2.5 px-3 border-b border-border w-28 text-center">{t('catalog.table.stock')}</TableHead>
                        <TableHead className="py-2.5 px-3 border-b border-border w-32 text-right">{t('catalog.table.price')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {products.map((product, idx) => (
                        <TableRow
                            key={product.id}
                            role="button"
                            tabIndex={0}
                            aria-label={product.name}
                            className="hover:bg-row-hover transition-colors group cursor-pointer border-b border-border dark:border-border last:border-0 focus-within:bg-accent"
                            onClick={() => onProductClick(product)}
                            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onProductClick(product); } }}
                        >
                            <TableCell className="py-2 px-3 text-center" onClick={(e) => e.stopPropagation()}>
                                <Checkbox
                                    checked={selectedIds.has(product.id)}
                                    onCheckedChange={() => toggleOne(product.id)}
                                    aria-label={`Select ${product.name}`}
                                />
                            </TableCell>
                            <TableCell className="py-2 px-3 text-xs text-muted-foreground text-center tabular-nums">
                                {idx + 1}
                            </TableCell>
                            <TableCell className="py-2 px-3">
                                <div className="flex items-center gap-2.5">
                                    <div className="w-8 h-8 rounded-md bg-muted dark:bg-muted flex items-center justify-center shrink-0 border border-border overflow-hidden">
                                        {product.main_image_url ? (
                                            <img src={product.main_image_url} alt="" className="w-full h-full object-contain" loading="lazy" />
                                        ) : (
                                            <Package className="w-3.5 h-3.5 text-muted-foreground dark:text-muted-foreground" aria-hidden="true" />
                                        )}
                                    </div>
                                    <div className="flex flex-col min-w-0">
                                        <span className="text-sm font-semibold text-foreground truncate group-hover:text-primary transition-colors">
                                            {product.name}
                                        </span>
                                        <span className="text-xs text-muted-foreground truncate">
                                            {product.category_data?.name || ''}
                                        </span>
                                    </div>
                                </div>
                            </TableCell>
                            <TableCell className="py-2 px-3">
                                <div className="flex flex-col gap-0.5">
                                    <span className="text-sm font-mono font-semibold text-foreground">
                                        {product.sku || '—'}
                                    </span>
                                    {product.gost_drawing && (
                                        <span className="flex items-center gap-1 text-xs text-muted-foreground">
                                            <FileText size={10} aria-hidden="true" />
                                            {product.gost_drawing}
                                        </span>
                                    )}
                                </div>
                            </TableCell>
                            <TableCell className="py-2 px-3">
                                <div className="flex flex-col">
                                    <span className="text-sm text-foreground dark:text-muted-foreground truncate">
                                        {product.brand_name || '—'}
                                    </span>

                                </div>
                            </TableCell>
                            <TableCell className="py-2 px-3 text-center">
                                <span className="text-xs font-medium text-muted-foreground bg-muted dark:bg-muted px-1.5 py-0.5 rounded-md">
                                    {product.uom_data?.code || t('catalog.table.defaultUnit')}
                                </span>
                            </TableCell>
                            <TableCell className="py-2 px-3 text-center">
                                <StatusBadge
                                    label={t(`catalog.stock.${product.stock_status || 'IN_STOCK'}`)}
                                    variant={getStockVariant(product.stock_status || 'IN_STOCK')}
                                />
                            </TableCell>
                            <TableCell className="py-2 px-3 text-right">
                                {canSeePrices ? (
                                    <div className="flex flex-col items-end">
                                        <span className="text-sm font-semibold text-foreground tabular-nums">
                                            {Number(product.base_price).toLocaleString('ru-RU', { minimumFractionDigits: 2 })}
                                        </span>
                                        <span className="text-xs text-muted-foreground">
                                            {product.offers?.[0]?.currency_data?.code || 'USD'}
                                        </span>
                                    </div>
                                ) : (
                                    <div className="flex items-center justify-end gap-1.5 text-warning">
                                        <LockIcon size={12} aria-hidden="true" />
                                        <span className="text-xs text-warning">{t('catalog.priceHidden')}</span>
                                    </div>
                                )}
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
    );
};
