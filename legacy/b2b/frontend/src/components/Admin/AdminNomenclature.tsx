import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Plus, Search, Archive, Loader2, FileSpreadsheet, Edit, Boxes, Filter, Tag, Package } from 'lucide-react';
import { Product } from '../../api/catalogApi';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Card, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { NomenclatureSlidePanel } from './NomenclatureSlidePanel';
import { ExcelUploadModal } from './ExcelUploadModal';
import { useProducts, useCreateProduct, useUpdateProduct, useDeleteProduct, useDomainTypes } from '../../hooks/useCatalog';
import { getDomainVisual } from '../../config/domainConfig';
import { PageShell, LoadingRows, EmptyState } from '../../pages/shared/PageShell';

export const AdminNomenclature: React.FC = () => {
    const { t } = useTranslation();
    // UI states
    const [searchTerm, setSearchTerm] = useState('');
    const [isPanelOpen, setIsPanelOpen] = useState(false);
    const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
    const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
    const [, setOpenMenuId] = useState<number | null>(null);
    const [selectedIds, setSelectedIds] = useState<number[]>([]);
    const [domainFilter, setDomainFilter] = useState<string>('ALL');

    // React Query Hooks
    const { data: domainTypes = [] } = useDomainTypes();
    const { data: products = [], isLoading, refetch } = useProducts({
        search: searchTerm || undefined,
        domain_type: domainFilter === 'ALL' ? undefined : domainFilter
    });

    const createMutation = useCreateProduct();
    const updateMutation = useUpdateProduct();
    const deleteMutation = useDeleteProduct();

    // Close menu when clicking outside
    useEffect(() => {
        const handleClickOutside = () => setOpenMenuId(null);
        document.addEventListener('click', handleClickOutside);
        return () => document.removeEventListener('click', handleClickOutside);
    }, []);

    const handleSavePanel = async (data: Partial<Product> & { equipment_group_ids?: number[] }) => {
        try {
            if (selectedProduct) {
                await updateMutation.mutateAsync({ id: selectedProduct.id, data });
            } else {
                await createMutation.mutateAsync(data);
            }
            setIsPanelOpen(false);
            setSelectedProduct(null);
        } catch (err: unknown) {
            const e = err as { response?: { data?: { detail?: string } }; message?: string };
            toast.error(t('common.error') + ': ' + (e.response?.data?.detail || e.message || 'Unknown error'));
        }
    };

    const handleCreateClick = () => {
        setSelectedProduct(null);
        setIsPanelOpen(true);
    };

    const handleEditClick = (product: Product) => {
        setSelectedProduct(product);
        setIsPanelOpen(true);
    };

    const handleDelete = async (id: number) => {
        if (!confirm(t('admin.nomenclature.confirmDelete'))) return;
        try {
            await deleteMutation.mutateAsync(id);
        } catch {
            toast.error(t('admin.nomenclature.operationFailed'));
        }
    };

    const toggleSelectAll = () => {
        if (selectedIds.length === products.length) {
            setSelectedIds([]);
        } else {
            setSelectedIds(products.map(p => p.id));
        }
    };

    const toggleSelect = (id: number) => {
        setSelectedIds(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]);
    };

    const handleBulkDelete = async () => {
        if (!selectedIds.length || !confirm(t('admin.nomenclature.confirmBulkDelete', { count: selectedIds.length }))) return;
        try {
            await Promise.all(selectedIds.map(id => deleteMutation.mutateAsync(id)));
            setSelectedIds([]);
        } catch {
            toast.error(t('admin.nomenclature.bulkOperationFailed'));
        }
    };

    const uniqueDomainCount = new Set(products.map(p => p.domain_type_name).filter(Boolean)).size;

    const stats = [
        { label: t('admin.nomenclature.stats.total'), value: String(products.length) },
        { label: t('admin.nomenclature.stats.domains'), value: String(uniqueDomainCount) },
    ];

    const actions = [
        { label: t('admin.nomenclature.batchSync'), variant: 'outline' as const, onClick: () => setIsUploadModalOpen(true) },
        { label: t('admin.nomenclature.createSKU'), onClick: handleCreateClick },
    ];

    return (
        <PageShell
            title={t('admin.nomenclature.title')}
            description={t('admin.nomenclature.description')}
            icon={<Package className="h-5 w-5" />}
            stats={stats}
            actions={actions}
        >
            {/* Toolbar */}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <div className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                    <Input
                        type="text"
                        placeholder={t('admin.nomenclature.searchPlaceholder')}
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="pl-9"
                    />
                </div>

                <div className="flex items-center gap-1">
                    <Filter className="h-3.5 w-3.5 text-muted-foreground mr-1" />
                    {[{ code: 'ALL', name: t('common.all') }, ...domainTypes].map((d) => (
                        <Button
                            key={d.code}
                            variant={domainFilter === d.code ? 'secondary' : 'ghost'}
                            size="sm"
                            onClick={() => setDomainFilter(d.code)}
                            className="text-xs"
                        >
                            {d.code === 'ALL' ? t('common.all') : t(getDomainVisual(d.code).shortLabelKey, d.name)}
                        </Button>
                    ))}
                </div>

                {selectedIds.length > 0 && (
                    <div className="flex items-center gap-2 bg-destructive/5 px-2 py-1 rounded">
                        <span className="text-xs font-semibold text-destructive">{t('admin.nomenclature.selected', { count: selectedIds.length })}</span>
                        <Button
                            variant="destructive"
                            size="icon-xs"
                            onClick={handleBulkDelete}
                        >
                            <Archive className="w-3.5 h-3.5" />
                        </Button>
                    </div>
                )}
            </div>

            {/* Table */}
            <Card>
                <CardContent className="p-0">
                    {isLoading ? <LoadingRows rows={5} /> : products.length === 0 ? (
                        <EmptyState icon={<Boxes className="h-5 w-5" />} message={t('admin.nomenclature.emptyState')} />
                    ) : (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead className="w-10">
                                        <Checkbox
                                            checked={selectedIds.length === products.length && products.length > 0}
                                            onCheckedChange={toggleSelectAll}
                                            aria-label={t('common.selectAll')}
                                        />
                                    </TableHead>
                                    <TableHead>{t('admin.nomenclature.columns.objectDescription')}</TableHead>
                                    <TableHead>{t('admin.nomenclature.columns.domainSegment')}</TableHead>
                                    <TableHead>{t('admin.nomenclature.columns.baseValue')}</TableHead>
                                    <TableHead>{t('admin.nomenclature.columns.eqGroups')}</TableHead>
                                    <TableHead className="text-right">{t('admin.nomenclature.columns.protoActions')}</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {products.map((product) => (
                                    <TableRow key={product.id} className="group">
                                        <TableCell className="w-10">
                                            <Checkbox
                                                checked={selectedIds.includes(product.id)}
                                                onCheckedChange={() => toggleSelect(product.id)}
                                                aria-label={t('common.select')}
                                            />
                                        </TableCell>
                                        <TableCell className="max-w-xs">
                                            <div className="flex flex-col min-w-0">
                                                <span className="text-sm font-medium text-foreground truncate group-hover:text-primary transition-colors">{product.name}</span>
                                                <span className="text-xs text-muted-foreground mt-0.5">{product.sku || '—'}</span>
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium border ${getDomainVisual(product.domain_type_name).badgeClass}`}>
                                                <Tag className="w-2.5 h-2.5 mr-1" /> {product.domain_type_name}
                                            </span>
                                        </TableCell>
                                        <TableCell>
                                            <div className="text-sm font-medium tabular-nums">{parseFloat(product.base_price).toLocaleString()} {product.currency_data?.code || 'USD'}</div>
                                            <div className="text-xs text-muted-foreground mt-0.5">per {product.uom_data?.name || 'unit'}</div>
                                        </TableCell>
                                        <TableCell className="min-w-[140px]">
                                            <div className="flex flex-wrap gap-1">
                                                {product.equipment_groups && product.equipment_groups.length > 0 ? (
                                                    product.equipment_groups.map(g => (
                                                        <span key={g.id} className="text-xs font-medium px-1.5 py-0.5 bg-muted text-muted-foreground rounded border border-border">
                                                            {g.name}
                                                        </span>
                                                    ))
                                                ) : (
                                                    <span className="text-xs text-muted-foreground opacity-50">{t('admin.nomenclature.universal')}</span>
                                                )}
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-right">
                                            <div className="inline-flex items-center gap-1 opacity-40 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
                                                <Button
                                                    variant="ghost"
                                                    size="icon-xs"
                                                    onClick={() => handleEditClick(product)}
                                                >
                                                    <Edit className="w-3.5 h-3.5" />
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="icon-xs"
                                                    onClick={() => handleDelete(product.id)}
                                                    className="hover:text-destructive"
                                                >
                                                    <Archive className="w-3.5 h-3.5" />
                                                </Button>
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}
                </CardContent>
            </Card>

            <NomenclatureSlidePanel
                isOpen={isPanelOpen}
                onClose={() => setIsPanelOpen(false)}
                product={selectedProduct}
                onSave={handleSavePanel}
            />

            <ExcelUploadModal
                isOpen={isUploadModalOpen}
                onClose={() => {
                    setIsUploadModalOpen(false);
                    refetch();
                }}
            />
        </PageShell>
    );
};
