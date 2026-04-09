import React, { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { Search, ShieldAlert, ArrowRight, LayoutGrid, List, PanelLeftClose, PanelLeftOpen, Grid2X2, LayoutList, Train, Package, Wrench, Clock } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Product } from '../../api/catalogApi';
import { useAuthStore } from '../../store/authStore';
import { useDomainStore } from '../../store/domainStore';
import { useLoadingStore } from '../../store/loadingStore';
import { DomainAdaptiveSidebar } from './DomainAdaptiveSidebar';
import { useProducts } from '../../hooks/useCatalog';
import { CatalogGrid } from './subcomponents/CatalogGrid';
import { CatalogTable } from './subcomponents/CatalogTable';
import { ProductDetailModal } from './subcomponents/ProductDetailModal';
import { EmptyState } from '@/components/ui/EmptyState';
import { CatalogGridSkeleton } from '@/components/ui/LoadingSkeleton';
import { Button } from '@/components/ui/button';
import { clsx } from 'clsx';

const domainIcons: Record<string, React.ReactNode> = {
  RAILWAY_MACHINERY: <Train size={12} className="text-muted-foreground" />,
  GENERAL_GOODS: <Package size={12} className="text-primary" />,
  SERVICES: <Wrench size={12} className="text-primary" />,
};

const RECENT_SEARCHES_KEY = 'railtech-recent-searches';

function getRecentSearches(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_SEARCHES_KEY) || '[]').slice(0, 5);
  } catch { return []; }
}

function saveRecentSearch(query: string) {
  const recent = getRecentSearches().filter(s => s !== query);
  recent.unshift(query);
  localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(recent.slice(0, 5)));
}

type SortOption = 'name' | 'price_asc' | 'price_desc' | 'stock';
export type GridDensity = 'compact' | 'normal' | 'comfortable';

export const PublicCatalog: React.FC = () => {
    const { t } = useTranslation();
    const { isAuthenticated, kyc_status, role } = useAuthStore();
    const { activeDomain, filters } = useDomainStore();
    const { setPageLoading } = useLoadingStore();

    const [searchQuery, setSearchQuery] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [showSuggestions, setShowSuggestions] = useState(false);
    const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
    const [viewMode, setViewMode] = useState<'grid' | 'table'>('grid');
    const [density, setDensity] = useState<GridDensity>('normal');
    const [sortBy, setSortBy] = useState<SortOption>('name');
    const [suggestionIndex, setSuggestionIndex] = useState(-1);
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

    const searchRef = useRef<HTMLDivElement>(null);

    // Дебаунс поиска: запрос идёт только через 350мс после последнего нажатия
    useEffect(() => {
        const timer = setTimeout(() => setDebouncedSearch(searchQuery), 350);
        return () => clearTimeout(timer);
    }, [searchQuery]);

    const { data: products = [], isLoading } = useProducts({
        domain_type: activeDomain || undefined,
        category: filters.category || undefined,
        manufacturer: filters.manufacturer || undefined,
        equipment_groups: filters.equipment_groups || undefined,
        stock_status: filters.stock_status || undefined,
        search: debouncedSearch || undefined,
    });

    // Синхронизируем состояние загрузки с глобальным баром (после объявления isLoading)
    useEffect(() => {
        setPageLoading(isLoading);
    }, [isLoading, setPageLoading]);

    const [recentSearches, setRecentSearches] = useState<string[]>(getRecentSearches);

    const suggestions = useMemo(() => {
        if (searchQuery.length < 2) return [];
        return products.slice(0, 8);
    }, [products, searchQuery]);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (searchRef.current && !searchRef.current.contains(event.target as Node)) {
                setShowSuggestions(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    useEffect(() => { setSuggestionIndex(-1); }, [suggestions]);

    const canSeePrices = isAuthenticated && (role === 'ADMIN' || kyc_status === 'L2_VERIFIED' || kyc_status === 'L3_CONTRACTED');

    const sortedProducts = useMemo(() => {
        return [...products].sort((a, b) => {
            if (sortBy === 'price_asc') return Number(a.base_price) - Number(b.base_price);
            if (sortBy === 'price_desc') return Number(b.base_price) - Number(a.base_price);
            if (sortBy === 'stock') {
                const order: Record<string, number> = { IN_STOCK: 0, EXPECTED: 1, ON_ORDER: 2 };
                return (order[a.stock_status || 'ON_ORDER'] ?? 3) - (order[b.stock_status || 'ON_ORDER'] ?? 3);
            }
            return a.name.localeCompare(b.name);
        });
    }, [products, sortBy]);

    const handleSearchKeyDown = useCallback(
        (e: React.KeyboardEvent) => {
            if (!showSuggestions || suggestions.length === 0) return;
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                setSuggestionIndex(i => Math.min(i + 1, suggestions.length - 1));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setSuggestionIndex(i => Math.max(i - 1, 0));
            } else if (e.key === 'Enter' && suggestionIndex >= 0) {
                e.preventDefault();
                setSelectedProduct(suggestions[suggestionIndex]);
                setShowSuggestions(false);
            } else if (e.key === 'Escape') {
                setShowSuggestions(false);
            }
        },
        [showSuggestions, suggestions, suggestionIndex],
    );

    const sortLabels: Record<SortOption, string> = {
        name: t('catalog.table.name'),
        price_asc: `${t('catalog.table.price')} ↑`,
        price_desc: `${t('catalog.table.price')} ↓`,
        stock: t('catalog.table.stock'),
    };

    const densityOptions: { value: GridDensity; icon: React.ElementType; label: string }[] = [
        { value: 'comfortable', icon: Grid2X2,   label: t('catalog.density.comfortable') },
        { value: 'normal',      icon: LayoutGrid, label: t('catalog.density.normal') },
        { value: 'compact',     icon: LayoutList, label: t('catalog.density.compact') },
    ];

    return (
        <div className="flex h-full min-h-0 bg-muted overflow-hidden">
            {/* ─── Sidebar (desktop) ─── */}
            {sidebarOpen && (
                <div
                    className={clsx(
                        'border-r border-border bg-card hidden lg:block overflow-hidden shrink-0 transition-all duration-200',
                        sidebarCollapsed ? 'w-[52px]' : 'w-[210px]'
                    )}
                >
                    <DomainAdaptiveSidebar isCollapsed={sidebarCollapsed} />
                </div>
            )}

            {/* ─── Main Content ─── */}
            <div className="flex-1 flex flex-col min-w-0 bg-card">
                {/* Toolbar */}
                <div className="h-11 bg-card border-b border-border flex items-center justify-between px-3 shrink-0 z-20">
                    <div className="flex items-center gap-2">
                        {/* Sidebar toggle */}
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => {
                                if (sidebarOpen && !sidebarCollapsed) {
                                    setSidebarCollapsed(true);
                                } else if (sidebarOpen && sidebarCollapsed) {
                                    setSidebarOpen(false);
                                    setSidebarCollapsed(false);
                                } else {
                                    setSidebarOpen(true);
                                }
                            }}
                            aria-label={sidebarOpen ? t('catalog.sidebar.collapse') : t('catalog.sidebar.expand')}
                            className="hidden lg:flex p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                        >
                            {sidebarOpen ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}
                        </Button>

                        {/* Search */}
                        <div className="flex items-center gap-3 flex-1 max-w-xl relative" ref={searchRef}>
                            <Search size={16} className="text-muted-foreground absolute left-3" aria-hidden="true" />
                            <input
                                type="search"
                                value={searchQuery}
                                onChange={e => { setSearchQuery(e.target.value); setShowSuggestions(true); }}
                                onKeyDown={handleSearchKeyDown}
                                onFocus={() => searchQuery.length >= 2 && setShowSuggestions(true)}
                                placeholder={t('catalog.searchPlaceholder')}
                                aria-label={t('common.search')}
                                aria-expanded={showSuggestions && suggestions.length > 0}
                                aria-autocomplete="list"
                                role="combobox"
                                className="w-full h-8 bg-muted border border-border text-sm pl-10 pr-3 rounded-lg outline-none focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all placeholder:text-muted-foreground"
                            />
                            {showSuggestions && (suggestions.length > 0 || (searchQuery.length < 2 && recentSearches.length > 0)) && (
                                <ul
                                    role="listbox"
                                    className="absolute top-full left-0 right-0 mt-1 bg-card border border-border shadow-xl rounded-xl z-50 overflow-hidden max-h-[400px] overflow-y-auto"
                                >
                                    {/* Recent searches */}
                                    {searchQuery.length < 2 && recentSearches.length > 0 && (
                                        <>
                                            <li className="px-3 py-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider bg-muted flex items-center gap-1.5">
                                                <Clock size={10} /> {t('catalog.recentSearches')}
                                            </li>
                                            {recentSearches.map((q) => (
                                                <li
                                                    key={q}
                                                    role="option"
                                                    onClick={() => { setSearchQuery(q); setShowSuggestions(false); }}
                                                    className="px-3 py-2 cursor-pointer border-b border-border flex items-center gap-2 hover:bg-muted text-sm text-muted-foreground"
                                                >
                                                    <Clock size={12} className="text-muted-foreground/60" /> {q}
                                                </li>
                                            ))}
                                        </>
                                    )}
                                    {/* Product suggestions with domain icons */}
                                    {suggestions.map((p, idx) => (
                                        <li
                                            key={p.id}
                                            role="option"
                                            aria-selected={idx === suggestionIndex}
                                            onClick={() => {
                                                setSelectedProduct(p);
                                                setShowSuggestions(false);
                                                if (searchQuery.length >= 2) saveRecentSearch(searchQuery);
                                                setRecentSearches(getRecentSearches());
                                            }}
                                            className={clsx(
                                                'px-3 py-2.5 cursor-pointer border-b border-border last:border-0 flex justify-between items-center transition-colors',
                                                idx === suggestionIndex
                                                    ? 'bg-accent'
                                                    : 'hover:bg-muted',
                                            )}
                                        >
                                            <div className="flex items-center gap-2.5 min-w-0">
                                                <span className="shrink-0 flex items-center justify-center w-6 h-6 rounded bg-muted">
                                                    {domainIcons[p.domain_type_name ?? ''] ?? <Package size={12} className="text-muted-foreground" />}
                                                </span>
                                                <div className="flex flex-col min-w-0">
                                                    <span className="text-sm font-semibold text-foreground truncate">{p.name}</span>
                                                    <span className="text-xs text-muted-foreground mt-0.5">
                                                        {p.sku ?? '—'}{p.gost_drawing ? ` · ${p.gost_drawing}` : ''}{p.manufacturer_data?.name ? ` · ${p.manufacturer_data.name}` : ''}
                                                    </span>
                                                </div>
                                            </div>
                                            <ArrowRight size={14} className="text-muted-foreground/60 shrink-0" aria-hidden="true" />
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </div>

                    <div className="flex items-center gap-2 pl-3 border-l border-border ml-3 h-full">
                        {/* Sort */}
                        <select
                            value={sortBy}
                            onChange={e => setSortBy(e.target.value as SortOption)}
                            aria-label={t('common.filters')}
                            className="h-7 bg-muted border border-border text-xs font-semibold text-muted-foreground rounded-md px-2 focus-ring hidden sm:block"
                        >
                            {Object.entries(sortLabels).map(([value, label]) => (
                                <option key={value} value={value}>{label}</option>
                            ))}
                        </select>

                        {/* Единый контрол: вид + плотность в одной группе */}
                        <div className="flex bg-muted border border-border rounded-md p-0.5 gap-0.5">
                            {/* Режим таблица */}
                            <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => setViewMode('table')}
                                aria-label={t('catalog.tableView')}
                                aria-pressed={viewMode === 'table'}
                                title={t('catalog.tableView')}
                                className={clsx('p-1.5 h-auto w-auto rounded transition-all', viewMode === 'table' ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground')}
                            >
                                <List size={14} />
                            </Button>

                            {/* Разделитель */}
                            <div className="w-px bg-border my-0.5" aria-hidden="true" />

                            {/* Плотность плитки — только на sm+ */}
                            {densityOptions.map(({ value, icon: Icon, label }) => (
                                <Button
                                    key={value}
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => { setViewMode('grid'); setDensity(value); }}
                                    title={label}
                                    aria-label={label}
                                    aria-pressed={viewMode === 'grid' && density === value}
                                    className={clsx(
                                        'p-1.5 h-auto w-auto rounded transition-all hidden sm:flex items-center',
                                        viewMode === 'grid' && density === value
                                            ? 'bg-foreground text-background'
                                            : 'text-muted-foreground hover:text-foreground'
                                    )}
                                >
                                    <Icon size={14} />
                                </Button>
                            ))}

                            {/* Плитка (fallback для мобильных — только одна кнопка) */}
                            <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => setViewMode('grid')}
                                aria-label={t('catalog.gridView')}
                                aria-pressed={viewMode === 'grid'}
                                title={t('catalog.gridView')}
                                className={clsx('p-1.5 h-auto w-auto rounded transition-all sm:hidden', viewMode === 'grid' ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground')}
                            >
                                <LayoutGrid size={14} />
                            </Button>
                        </div>

                        {!isLoading && (
                            <span className="hidden lg:inline text-xs text-muted-foreground ml-1 tabular-nums">
                                {t('catalog.totalItems', { count: products.length })}
                            </span>
                        )}
                    </div>
                </div>

                {/* Price restriction banner */}
                {!canSeePrices && (
                    <div className="bg-muted border-b border-border px-4 py-2 flex items-center justify-between shrink-0">
                        <div className="flex items-center gap-2 text-warning text-sm font-medium">
                            <ShieldAlert size={16} aria-hidden="true" />
                            {t('catalog.priceHidden')}
                        </div>
                        <Link to="/register" className="text-sm font-semibold text-primary hover:underline focus-ring rounded">
                            {t('kyc.banner.action')} →
                        </Link>
                    </div>
                )}

                {/* Content area */}
                <div className="flex-1 overflow-hidden relative">
                    <div className="w-full h-full p-4 overflow-auto custom-scrollbar">
                        {isLoading ? (
                            <CatalogGridSkeleton count={density === 'compact' ? 12 : density === 'comfortable' ? 4 : 8} />
                        ) : products.length === 0 ? (
                            <EmptyState
                                title={searchQuery ? t('catalog.noResults') : t('catalog.emptyState')}
                                description={searchQuery ? t('catalog.noResultsHint') : t('catalog.emptyStateHint')}
                                action={searchQuery ? { label: t('common.reset'), onClick: () => { setSearchQuery(''); setDebouncedSearch(''); } } : undefined}
                            />
                        ) : (
                            viewMode === 'table' ? (
                                <CatalogTable products={sortedProducts} onProductClick={setSelectedProduct} canSeePrices={canSeePrices} />
                            ) : (
                                <CatalogGrid products={sortedProducts} onProductClick={setSelectedProduct} canSeePrices={canSeePrices} density={density} />
                            )
                        )}
                    </div>
                </div>
            </div>

            {/* Mobile sidebar overlay */}
            <ProductDetailModal product={selectedProduct} onClose={() => setSelectedProduct(null)} canSeePrices={canSeePrices} />
        </div>
    );
};
