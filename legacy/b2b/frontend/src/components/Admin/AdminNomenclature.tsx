import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Search, Archive, Loader2, FileSpreadsheet, Edit, Boxes, Filter, Tag } from 'lucide-react';
import { Product } from '../../api/catalogApi';
import { Button } from '@/components/ui/button';
import { NomenclatureSlidePanel } from './NomenclatureSlidePanel';
import { ExcelUploadModal } from './ExcelUploadModal';
import { useProducts, useCreateProduct, useUpdateProduct, useDeleteProduct } from '../../hooks/useCatalog';

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
            alert(t('common.error') + ': ' + (e.response?.data?.detail || e.message || 'Unknown error'));
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
            alert(t('admin.nomenclature.operationFailed'));
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
            alert(t('admin.nomenclature.bulkOperationFailed'));
        }
    };

    return (
        <div className="p-4 h-full flex flex-col space-y-4 animate-in fade-in duration-300">
            {/* Header Section */}
            <div className="flex items-end justify-between border-b border-border pb-3">
                <div>
                    <h1 className="text-xl font-black tracking-tight text-foreground uppercase leading-none">
                        {t('admin.nomenclature.masterTitle')} <span className="text-primary">{t('admin.nomenclature.masterHighlight')}</span>
                    </h1>
                    <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest leading-none mt-1">
                        {t('admin.nomenclature.subtitle')}
                    </p>
                </div>

                <div className="flex gap-2">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setIsUploadModalOpen(true)}
                        className="text-xs font-black uppercase tracking-widest active:scale-95"
                    >
                        <FileSpreadsheet className="w-3.5 h-3.5" /> {t('admin.nomenclature.batchSync')}
                    </Button>
                    <Button
                        size="sm"
                        onClick={handleCreateClick}
                        className="text-xs font-black uppercase tracking-widest active:scale-95"
                    >
                        <Plus className="w-3.5 h-3.5" /> {t('admin.nomenclature.createSKU')}
                    </Button>
                </div>
            </div>

            {/* Smart Toolbar */}
            <div className="bg-card border border-border rounded p-2 flex flex-col md:flex-row gap-2 items-center shadow-sm font-mono">
                <div className="relative flex-1 w-full">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                    <input 
                        type="text" 
                        placeholder={t('admin.nomenclature.searchPlaceholder')}
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="w-full pl-9 pr-4 py-1.5 bg-muted border border-border rounded text-[11px] font-mono focus:ring-1 focus:ring-primary/50 outline-none transition-all text-foreground"
                    />
                </div>

                <div className="flex items-center gap-1 border-l border-border ml-2 pl-2">
                    <Filter className="w-3.5 h-3.5 text-muted-foreground mr-2" />
                    {['ALL', 'RAILWAY_MACHINERY', 'GENERAL_GOODS', 'SERVICES'].map((domain) => (
                        <Button
                            key={domain}
                            variant={domainFilter === domain ? 'secondary' : 'ghost'}
                            size="xs"
                            onClick={() => setDomainFilter(domain)}
                            className="text-[9px] font-black uppercase tracking-widest"
                        >
                            {domain === 'ALL' ? 'GLOBAL' : domain === 'RAILWAY_MACHINERY' ? 'RAIL' : domain === 'GENERAL_GOODS' ? 'GOODS' : 'SVCS'}
                        </Button>
                    ))}
                </div>

                {selectedIds.length > 0 && (
                    <div className="flex items-center gap-2 pl-4 border-l border-border ml-2 bg-destructive/5 px-2 py-1 rounded">
                        <span className="text-[9px] font-black text-destructive uppercase tracking-widest">{t('admin.nomenclature.selected', { count: selectedIds.length })}</span>
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

            {/* Nomenclature Table */}
            <div className="bg-card border border-border rounded shadow-sm flex-1 overflow-hidden font-mono">
                <div className="h-full overflow-auto custom-scrollbar">
                    <table className="w-full text-left border-collapse">
                        <thead className="sticky top-0 z-10 bg-muted text-muted-foreground text-xs font-black uppercase tracking-widest border-b border-border">
                            <tr>
                                <th className="px-4 py-3 w-10">
                                    <input 
                                        type="checkbox" 
                                        checked={selectedIds.length === products.length && products.length > 0}
                                        onChange={toggleSelectAll}
                                        className="w-4 h-4 rounded-sm border-border text-primary focus:ring-primary transition-all cursor-pointer opacity-70" 
                                    />
                                </th>
                                <th className="px-4 py-3">{t('admin.nomenclature.columns.objectDescription')}</th>
                                <th className="px-4 py-3">{t('admin.nomenclature.columns.domainSegment')}</th>
                                <th className="px-4 py-3">{t('admin.nomenclature.columns.baseValue')}</th>
                                <th className="px-4 py-3">{t('admin.nomenclature.columns.eqGroups')}</th>
                                <th className="px-4 py-3 text-right">{t('admin.nomenclature.columns.protoActions')}</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {isLoading ? (
                                <tr>
                                    <td colSpan={6} className="px-4 py-12 text-center text-muted-foreground text-xs uppercase font-bold tracking-widest leading-none">
                                        <div className="flex items-center justify-center gap-2">
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                            {t('admin.nomenclature.syncingData')}
                                        </div>
                                    </td>
                                </tr>
                            ) : products.length === 0 ? (
                                <tr>
                                    <td colSpan={6} className="px-4 py-12 text-center text-muted-foreground">
                                        <div className="flex flex-col items-center justify-center">
                                            <Boxes className="w-8 h-8 mb-2 opacity-20" />
                                            <p className="text-xs uppercase font-black tracking-widest">{t('admin.nomenclature.emptyState')}</p>
                                        </div>
                                    </td>
                                </tr>
                            ) : (
                                products.map((product) => (
                                    <tr key={product.id} className="group hover:bg-muted/50 transition-colors border-l-2 border-transparent hover:border-primary">
                                        <td className="px-4 py-3 w-10">
                                            <input 
                                                type="checkbox" 
                                                checked={selectedIds.includes(product.id)}
                                                onChange={() => toggleSelect(product.id)}
                                                className="w-4 h-4 rounded-sm border-border text-primary focus:ring-primary transition-all cursor-pointer opacity-70" 
                                            />
                                        </td>
                                        <td className="px-4 py-3 max-w-xs">
                                            <div className="flex flex-col min-w-0">
                                                <span className="text-[11px] font-black text-foreground uppercase truncate group-hover:text-primary transition-colors">{product.name}</span>
                                                <span className="text-[9px] font-bold text-muted-foreground uppercase tracking-widest mt-0.5">{product.sku || 'SKU_MISSING'}</span>
                                            </div>
                                        </td>
                                        <td className="px-4 py-3">
                                            <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[8px] font-black uppercase tracking-widest border ${
                                                product.domain_type_name === 'RAILWAY_MACHINERY' ? 'bg-primary/10 text-primary border-primary/20' :
                                                product.domain_type_name === 'SERVICES' ? 'bg-amber-500/10 text-amber-500 border-amber-500/20' :
                                                'bg-muted text-muted-foreground border-border'
                                            }`}>
                                                <Tag className="w-2.5 h-2.5 mr-1" /> {product.domain_type_name}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="text-xs font-black text-foreground font-mono leading-none">{parseFloat(product.base_price).toLocaleString()} {product.currency_data?.code || 'USD'}</div>
                                            <div className="text-[8px] text-muted-foreground font-bold uppercase tracking-tight mt-1">per {product.uom_data?.name || 'unit'}</div>
                                        </td>
                                        <td className="px-4 py-3 min-w-[140px]">
                                            <div className="flex flex-wrap gap-1">
                                                {product.equipment_groups && product.equipment_groups.length > 0 ? (
                                                    product.equipment_groups.map(g => (
                                                        <span key={g.id} className="text-[8px] font-black px-1.5 py-0.5 bg-muted text-muted-foreground rounded border border-border uppercase tracking-tighter">
                                                            {g.name}
                                                        </span>
                                                    ))
                                                ) : (
                                                    <span className="text-[8px] text-muted-foreground font-bold uppercase tracking-widest opacity-50">{t('admin.nomenclature.universal')}</span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-4 py-3 text-right">
                                            <div className="inline-flex items-center gap-1 opacity-40 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
                                                <Button
                                                    variant="ghost"
                                                    size="icon-xs"
                                                    onClick={() => handleEditClick(product)}
                                                    title="Modify Record"
                                                >
                                                    <Edit className="w-3.5 h-3.5" />
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="icon-xs"
                                                    onClick={() => handleDelete(product.id)}
                                                    className="hover:text-destructive"
                                                    title="Delete Index"
                                                >
                                                    <Archive className="w-3.5 h-3.5" />
                                                </Button>
                                            </div>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

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
        </div>
    );
};
