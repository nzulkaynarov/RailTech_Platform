import React from 'react';
import { useTranslation } from 'react-i18next';
import { Layers, Factory, Database, LayoutGrid, Package } from 'lucide-react';
import { useDomainStore } from '../../store/domainStore';
import { useProductsCount, useCategories, useManufacturers, useEquipmentGroups, useDomainTypes } from '../../hooks/useCatalog';
import { getDomainVisual } from '../../config/domainConfig';
import { Skeleton } from '@/components/ui/LoadingSkeleton';
import { Button } from '@/components/ui/button';
import { clsx } from 'clsx';

interface DomainAdaptiveSidebarProps {
    isCollapsed?: boolean;
}

export const DomainAdaptiveSidebar: React.FC<DomainAdaptiveSidebarProps> = ({ isCollapsed = false }) => {
    const { t } = useTranslation();
    const { activeDomain, setActiveDomain, filters, setFilter } = useDomainStore();
    const { data: domainTypes = [] } = useDomainTypes();

    const { data: categories = [], isLoading: catsLoading } = useCategories({
        domain_type: activeDomain || undefined
    });
    const { data: manufacturers = [], isLoading: mansLoading } = useManufacturers();
    const { isLoading: egLoading } = useEquipmentGroups();
    const { data: totalProducts = 0, isLoading: prodsLoading } = useProductsCount({
        domain_type: activeDomain || undefined
    });

    const isLoading = catsLoading || mansLoading || egLoading || prodsLoading;

    if (isCollapsed) {
        // Icon-only collapsed view
        return (
            <nav aria-label={t('catalog.sidebar.domain')} className="w-full flex flex-col h-full bg-background border-r border-border items-center py-4 gap-2">
                {/* All products */}
                <Button
                    variant="ghost"
                    size="icon"
                    title={t('catalog.sidebar.allProducts')}
                    onClick={() => setActiveDomain(null)}
                    className={clsx(
                        'w-10 h-10 rounded-lg flex items-center justify-center border transition-all',
                        activeDomain === null
                            ? 'bg-primary text-primary-foreground border-primary'
                            : 'border-border text-muted-foreground hover:border-muted-foreground/30'
                    )}
                >
                    <LayoutGrid size={16} />
                </Button>

                <div className="w-6 h-px bg-muted dark:bg-muted my-1" />

                {domainTypes.map(d => {
                    const visual = getDomainVisual(d.code);
                    const Icon = visual.icon ?? Package;
                    return (
                        <Button
                            key={d.id}
                            variant="ghost"
                            size="icon"
                            title={t(visual.labelKey, d.name)}
                            onClick={() => setActiveDomain(d.code)}
                            className={clsx(
                                'w-10 h-10 rounded-lg flex items-center justify-center border transition-all',
                                activeDomain === d.code
                                    ? 'bg-primary text-primary-foreground border-primary'
                                    : 'border-border text-muted-foreground hover:border-muted-foreground/30'
                            )}
                        >
                            <Icon size={16} />
                        </Button>
                    );
                })}
            </nav>
        );
    }

    return (
        <nav aria-label={t('catalog.sidebar.domain')} className="w-full flex flex-col h-full bg-background border-r border-border">
            {/* Domain Switcher */}
            <div className="p-3 border-b border-border bg-muted/50 dark:bg-black/10">
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2.5 px-1">
                    {t('catalog.sidebar.domain')}
                </h3>
                <div className="space-y-1">
                    {/* All products button */}
                    <Button
                        variant="ghost"
                        onClick={() => setActiveDomain(null)}
                        className={clsx(
                            'w-full flex items-center gap-2.5 h-8 px-2.5 rounded-lg transition-all text-left border text-sm justify-start',
                            activeDomain === null
                                ? 'bg-primary text-primary-foreground border-primary font-semibold'
                                : 'bg-transparent border-border text-muted-foreground hover:border-muted-foreground/30 dark:hover:border-muted-foreground/30'
                        )}
                    >
                        <LayoutGrid size={14} className="shrink-0" />
                        <span className="truncate">{t('catalog.sidebar.allProducts')}</span>
                    </Button>

                    {domainTypes.map(d => {
                        const visual = getDomainVisual(d.code);
                        const Icon = visual.icon ?? Package;
                        return (
                            <Button
                                key={d.id}
                                variant="ghost"
                                title={t(visual.labelKey, d.name)}
                                onClick={() => setActiveDomain(d.code)}
                                className={clsx(
                                    'w-full flex items-center gap-2.5 h-8 px-2.5 rounded-lg transition-all text-left border text-sm justify-start',
                                    activeDomain === d.code
                                        ? 'bg-primary text-primary-foreground border-primary font-semibold'
                                        : 'bg-transparent border-border text-muted-foreground hover:border-muted-foreground/30 dark:hover:border-muted-foreground/30'
                                )}
                            >
                                <Icon size={14} className="shrink-0" />
                                <span className="truncate">{t(visual.shortLabelKey, d.name)}</span>
                            </Button>
                        );
                    })}
                </div>
            </div>

            {/* Faceted Categories */}
            <div className="flex-1 overflow-y-auto py-3 px-3 custom-scrollbar bg-background">
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2.5 px-1 flex items-center gap-2">
                    <Layers className="w-3 h-3" aria-hidden="true" />
                    {t('catalog.filters.category')}
                </h3>
                <div className="space-y-0.5 border border-border dark:border-border p-1 rounded-lg bg-muted/30 dark:bg-black/10">
                    {isLoading ? (
                        <div className="space-y-1 p-1">
                            {Array.from({ length: 6 }).map((_, i) => (
                                <Skeleton key={i} className="h-6 w-full rounded-md" />
                            ))}
                        </div>
                    ) : categories.length === 0 ? (
                        <p className="text-xs text-muted-foreground px-2 py-3 text-center">
                            {t('catalog.sidebar.noCategories')}
                        </p>
                    ) : (
                        categories.map(cat => (
                            <Button
                                key={cat.id}
                                variant="ghost"
                                onClick={() => setFilter('category', cat.id === filters.category ? null : cat.id)}
                                className={clsx(
                                    'w-full flex items-center justify-between h-7 px-2.5 rounded-md transition-all text-left border text-sm',
                                    filters.category === cat.id
                                        ? 'bg-background text-primary border-border shadow-sm font-medium'
                                        : 'text-muted-foreground hover:text-foreground dark:hover:text-foreground border-transparent'
                                )}
                            >
                                <span className="text-xs truncate">{cat.name}</span>
                                {filters.category === cat.id && (
                                    <div className="w-1.5 h-1.5 bg-primary rounded-full shrink-0" />
                                )}
                            </Button>
                        ))
                    )}
                </div>
            </div>

            {/* Footer Stats */}
            <div className="p-3 border-t border-border bg-muted dark:bg-background">
                <div className="space-y-1.5">
                    <div className="flex justify-between items-center text-xs">
                        <span className="text-muted-foreground flex items-center gap-1.5">
                            <Database className="w-3 h-3" aria-hidden="true" />
                            {t('admin.dashboard.totalProducts')}
                        </span>
                        <span className="text-primary font-semibold tabular-nums">{totalProducts}</span>
                    </div>
                    <div className="flex justify-between items-center text-xs">
                        <span className="text-muted-foreground flex items-center gap-1.5">
                            <Factory className="w-3 h-3" aria-hidden="true" />
                            {t('catalog.table.manufacturer')}
                        </span>
                        <span className="text-muted-foreground font-semibold tabular-nums">{manufacturers.length}</span>
                    </div>
                </div>
            </div>
        </nav>
    );
};
