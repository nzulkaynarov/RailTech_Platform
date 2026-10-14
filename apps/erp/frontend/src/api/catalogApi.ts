import { runAiJob } from '@/lib/aiJob';
import { apiClient } from './client';
import { fetchAllPages } from './fetchAllPages';
import { PaginatedResponse } from './types';

export interface DomainTypeItem {
    id: number;
    code: string;
    name: string;
    sku_prefix: string;
    sort_order: number;
    is_active: boolean;
}

export interface Category {
    id: number;
    name: string;
    parent?: number | null;
    domain_type?: number | null;
    icon?: string | null;
    sort_order?: number;
    is_active?: boolean;
}

export interface ProductStatusItem {
    id: number;
    code: string;
    name: string;
}

export interface Manufacturer {
    id: number;
    // FK на master_data.Country; читаемое имя приходит отдельным полем.
    country?: number | null;
    country_name?: string | null;
    name: string;
}

export interface SupplierOffer {
    id: number;
    product?: number;
    supplier: number;
    supplier_data?: { id: number; name: string } | null;
    supplier_sku?: string;
    base_price: string;
    currency?: number | null;
    currency_data?: { id: number; code: string; symbol: string } | null;
    delivery_basis?: number | null;
    delivery_basis_data?: { id: number; code: string; name: string } | null;
    stock_status?: number | null;
    delivery_lead_time?: string;
    stock_quantity?: number;
    in_stock_lead_time_days?: number;
    order_lead_time_days?: number;
    min_order_qty?: number;
    /**
     * Окно действия цены (`YYYY-MM-DD`), эталон — Validity Start/End у
     * `product.supplierinfo` в Odoo. Пустая граница = открытая.
     */
    valid_from?: string | null;
    valid_until?: string | null;
    is_active?: boolean;
}

export interface Product {
    id: number;
    name: string;
    description: string;
    sku: string | null;
    status: number;
    status_name: string;
    status_code?: string;
    domain_type: number | string;
    domain_type_name: string;
    domain_type_code?: string;

    category?: number | null;
    category_data?: { id: number, name: string } | null;

    // The SELLER company that owns the listing (tenancy), NOT the OEM.
    owner_company_data?: { id: number; name: string; inn?: string; logo?: string | null } | null;

    // Canonical brand (catalog.Manufacturer / OEM). This is what catalog
    // displays show as "manufacturer/производитель".
    brand?: number | null;
    brand_name?: string | null;
    brand_country?: string | null;
    manufacturer_part_number?: string | null;
    /** Код ТН ВЭД — постоянный дом кода (PIM); КП наследует и замораживает. */
    hs_code?: string;

    /**
     * Полнота карточки — ВЫЧИСЛЯЕТСЯ сервером (Akeneo): `missing` называет, чего не хватает,
     * и публикация открывается сама, когда обязательное заполнено. Это заменило ручное
     * благословение платформы: до волны A опубликовать карточку мог только оператор.
     */
    completeness?: { percent: number; missing: { code: string; label: string }[]; is_publishable: boolean };
    /** Сколько КП спрашивали эту позицию — очередь наполнения сортируется по спросу (Ariba). */
    demand_count?: number;
    last_requested_at?: string | null;
    /** Заявка, из строки которой родилась карточка. */
    source_deal?: number | null;

    uom?: number | null;
    uom_data?: { id: number; code: string; name: string } | null;

    stock_status?: string | null;
    /**
     * Цена самого дешёвого активного оффера. `null` — офферов нет вовсе: раньше сервер
     * отдавал строку "0", и витрина печатала настоящий нулевой ценник (R1).
     * Срезается cost-gate'ом вместе с `base_price_currency` у того, кто не владелец.
     */
    base_price?: string | null;
    /** Валюта ТОГО ЖЕ оффера — форматировать цену без неё нельзя (оффер бывает в USD). */
    base_price_currency?: string | null;

    gost_drawing?: string | null;
    specifications?: {
        tech_specs?: string;
        [key: string]: string | number | boolean | null | undefined;
    } | null;

    images?: { id: number, image: string | null, image_url: string | null, is_main: boolean, alt_text?: string }[];
    documents?: { id: number, file: string | null, file_url: string | null, name: string }[];

    main_image_url?: string | null;
    main_document_url?: string | null;

    offers?: SupplierOffer[];
    created_at?: string;
    updated_at?: string;
}


/**
 * Параметры серверного списка товаров. Ровно то, что понимает `ProductViewSet`:
 * фильтры + `?search=` + `?ordering=` + постраничка. Клиентская пагинация поверх
 * первых 20 строк (до R1) врала и покупателю, и продавцу — теперь считает сервер.
 */
export interface ProductListParams {
    domain_type?: string;
    search?: string;
    category?: number;
    brand?: number;
    stock_status?: string;
    /** Только карточки своей компании (бэкенд: `?mine=1`). */
    mine?: boolean;
    /** Код статуса карточки: DRAFT / PUBLISHED / ARCHIVED. */
    status?: string;
    /**
     * Происхождение черновика — питает табы единого реестра (аудит §5.2):
     * `rfq` — кандидаты из заявок (есть спрос или исходная сделка), `manual` — заведённые руками.
     */
    origin?: 'rfq' | 'manual';
    /** DRF-порядок: `name`, `-demand_count`, … Пустая строка = порядок по умолчанию. */
    ordering?: string;
    /**
     * Составной порядок очереди наполнения (спрос → дата запроса → имя). Это НЕ то же,
     * что `ordering=-demand_count`: одним полем тай-брейкеры не выразить. Явный
     * пользовательский `ordering` имеет приоритет.
     */
    order?: 'demand';
    page?: number;
    page_size?: number;
}

function buildProductListQuery(params: ProductListParams): string {
    const query = new URLSearchParams();
    if (params.domain_type) query.append('domain_type__code', params.domain_type);
    if (params.search) query.append('search', params.search);
    if (params.category) query.append('category', String(params.category));
    if (params.brand) query.append('brand', String(params.brand));
    if (params.stock_status) query.append('stock_status', params.stock_status);
    if (params.mine) query.append('mine', '1');
    if (params.status) query.append('status', params.status);
    if (params.origin) query.append('origin', params.origin);
    if (params.ordering) query.append('ordering', params.ordering);
    if (params.order) query.append('order', params.order);
    if (params.page && params.page > 1) query.append('page', String(params.page));
    if (params.page_size) query.append('page_size', String(params.page_size));
    return query.toString();
}

export const catalogApi = {
    getDomainTypes: async (): Promise<DomainTypeItem[]> => {
        const response = await apiClient.get<DomainTypeItem[]>('catalog/domain-types/');
        return response.data;
    },

    /**
     * Страница списка ЦЕЛИКОМ — с `count`, а не только `results`. Витрина обязана
     * знать общее число: KPI «Всего позиций» и пагинатор считают именно по нему.
     */
    getProductsPage: async (params: ProductListParams = {}): Promise<PaginatedResponse<Product>> => {
        const query = buildProductListQuery(params);
        const response = await apiClient.get<PaginatedResponse<Product>>(
            `catalog/products/${query ? `?${query}` : ''}`,
        );
        return response.data;
    },

    getProducts: async (params?: {
        domain_type?: string,
        search?: string,
        category?: number,
        brand?: number,
        equipment_groups?: number,
        stock_status?: string,
        // Admin lists need every row (client-side search/sort/pager); follow all pages.
        fetchAll?: boolean,
    }): Promise<Product[]> => {
        let url = 'catalog/products/';
        if (params) {
            const query = new URLSearchParams();
            if (params.domain_type) query.append('domain_type__code', params.domain_type);
            if (params.search) query.append('search', params.search);
            if (params.category) query.append('category', params.category.toString());
            if (params.brand) query.append('brand', params.brand.toString());
            if (params.equipment_groups) query.append('equipment_groups', params.equipment_groups.toString());
            if (params.stock_status) query.append('stock_status', params.stock_status);
            if (query.toString()) url += `?${query.toString()}`;
        }
        if (params?.fetchAll) return fetchAllPages<Product>(url);
        const response = await apiClient.get<PaginatedResponse<Product>>(url);
        return response.data.results;
    },
    getProductsCount: async (params?: { domain_type?: string }): Promise<number> => {
        let url = 'catalog/products/';
        if (params?.domain_type) {
            url += `?domain_type__code=${params.domain_type}`;
        }
        // Use limit=1 to minimize payload size while getting the full count
        url += (url.includes('?') ? '&' : '?') + 'limit=1';
        const response = await apiClient.get<PaginatedResponse<Product>>(url);
        return response.data.count;
    },
    getCategories: async (params?: { domain_type?: string; fetchAll?: boolean }): Promise<Category[]> => {
        let url = 'catalog/categories/';
        if (params?.domain_type) {
            url += `?domain_type__code=${params.domain_type}`;
        }
        if (params?.fetchAll) return fetchAllPages<Category>(url);
        const response = await apiClient.get<PaginatedResponse<Category>>(url);
        return response.data.results;
    },
    getManufacturers: async (params?: { fetchAll?: boolean }): Promise<Manufacturer[]> => {
        if (params?.fetchAll) return fetchAllPages<Manufacturer>('catalog/manufacturers/');
        const response = await apiClient.get<PaginatedResponse<Manufacturer>>('catalog/manufacturers/');
        return response.data.results;
    },
    getProduct: async (id: number | string): Promise<Product> => {
        const response = await apiClient.get<Product>(`catalog/products/${id}/`);
        return response.data;
    },
    /** Очередь наполнения продавца: свои карточки, сначала самые спрашиваемые. */
    getMyCandidates: async (statusCode = 'DRAFT'): Promise<Product[]> => {
        const response = await apiClient.get<{ results?: Product[] } | Product[]>('catalog/products/', {
            params: { mine: 'true', status: statusCode, order: 'demand', page_size: 200 },
        });
        const body = response.data as { results?: Product[] };
        return body.results ?? (response.data as Product[]);
    },
    /** Worklist переклассификации: свои карточки, чей код ТН ВЭД выведен из редакции. */
    getReclassificationWorklist: async (): Promise<Product[]> => {
        const response = await apiClient.get<{ results?: Product[] } | Product[]>('catalog/products/', {
            params: { mine: 'true', needs_reclassification: 'true', page_size: 100 },
        });
        const body = response.data as { results?: Product[] };
        return body.results ?? (response.data as Product[]);
    },
    /** T4: пакетный подбор кодов (202 + ai-status). Возвращает task_id. */
    classifyHSCodes: async (productIds: number[]): Promise<{ task_id: string }> => {
        const response = await apiClient.post<{ task_id: string }>('catalog/products/hs-classify/', { product_ids: productIds });
        return response.data;
    },
    /** T4: применить ПОДТВЕРЖДЁННЫЕ человеком коды. */
    applyHSCodes: async (assignments: { product_id: number; code: string }[]): Promise<{ applied: number[]; skipped: { product_id: number; reason: string }[] }> => {
        const response = await apiClient.post<{ applied: number[]; skipped: { product_id: number; reason: string }[] }>('catalog/products/hs-apply/', { assignments });
        return response.data;
    },
    /** Кандидаты кода ТН ВЭД из справочника: текст → пословный поиск, цифры → ветка кода. */
    suggestHSCodes: async (q: string): Promise<{ code: string; name: string; level: number; score: number }[]> => {
        const response = await apiClient.get<{ candidates: { code: string; name: string; level: number; score: number }[] }>(
            'catalog/products/hs-suggest/', { params: { q } },
        );
        return response.data.candidates;
    },
    /** Мягкая валидация кода: known/active/name. Ничего не блокирует — только подсветка. */
    validateHSCode: async (code: string): Promise<{ known: boolean; active: boolean; name: string }> => {
        const response = await apiClient.get<{ known: boolean; active: boolean; name: string }>(
            'catalog/products/hs-validate/', { params: { code } },
        );
        return response.data;
    },
    /** Публикация карточки её ВЛАДЕЛЬЦЕМ (Amazon/Alibaba/Shopify), гейт — полнота. */
    /**
     * Жизненный цикл карточки (R2). Бенчмарк Shopify: Active → Draft двусторонне,
     * Archive отдельно и ОБРАТИМО — до этой волны продавец умел только публиковать,
     * а слитый дубль исчезал в архиве безвозвратно.
     */
    unpublishProduct: async (id: number): Promise<Product> => {
        const response = await apiClient.post<Product>(`catalog/products/${id}/unpublish/`);
        return response.data;
    },
    archiveProduct: async (id: number): Promise<Product> => {
        const response = await apiClient.post<Product>(`catalog/products/${id}/archive/`);
        return response.data;
    },
    restoreProduct: async (id: number): Promise<Product> => {
        const response = await apiClient.post<Product>(`catalog/products/${id}/restore/`);
        return response.data;
    },
    bulkArchiveProducts: async (ids: number[]): Promise<{ archived: number[]; skipped: { product_id: number; error: string }[] }> => {
        // Подчёркивание в пути — консистентность с историческим bulk_publish.
        const response = await apiClient.post<{ archived: number[]; skipped: { product_id: number; error: string }[] }>(
            'catalog/products/bulk_archive/', { product_ids: ids },
        );
        return response.data;
    },
    publishProduct: async (id: number): Promise<Product> => {
        const response = await apiClient.post<Product>(`catalog/products/${id}/publish/`, {});
        return response.data;
    },
    /** N4: покрытие каталога — доля строк КП, опирающихся на карточку (Ariba catalog spend). */
    getCatalogCoverage: async (): Promise<{
        lines_total: number; lines_with_product: number; percent: number; candidates_pending: number;
    }> => {
        const response = await apiClient.get<{
            lines_total: number; lines_with_product: number; percent: number; candidates_pending: number;
        }>('catalog/products/coverage/');
        return response.data;
    },
    /** N4: группы вероятных дублей своих карточек — система предлагает, человек решает. */
    getDuplicateSuggestions: async (): Promise<{
        groups: {
            survivor: { id: number; name: string; status_code: string | null };
            duplicates: { id: number; name: string; status_code: string | null }[];
        }[];
    }> => {
        const response = await apiClient.get<{
            groups: {
                survivor: { id: number; name: string; status_code: string | null };
                duplicates: { id: number; name: string; status_code: string | null }[];
            }[];
        }>('catalog/products/duplicate-suggestions/');
        return response.data;
    },
    /** N4: слить дубль в выжившую карточку (дубль уходит в архив, ссылки переезжают). */
    mergeProducts: async (survivorId: number, duplicateId: number): Promise<Product> => {
        const response = await apiClient.post<Product>(`catalog/products/${survivorId}/merge/`, {
            duplicate_id: duplicateId,
        });
        return response.data;
    },
    createProduct: async (data: Partial<Product>): Promise<Product> => {
        const response = await apiClient.post<Product>('catalog/products/', data);
        return response.data;
    },
    updateProduct: async (id: number, data: Partial<Product>): Promise<Product> => {
        const response = await apiClient.patch<Product>(`catalog/products/${id}/`, data);
        return response.data;
    },
    deleteProduct: async (id: number): Promise<void> => {
        await apiClient.delete(`catalog/products/${id}/`);
    },
    createCategory: async (data: Partial<Category>): Promise<Category> => {
        const response = await apiClient.post<Category>('catalog/categories/', data);
        return response.data;
    },
    updateCategory: async (id: number, data: Partial<Category>): Promise<Category> => {
        const response = await apiClient.patch<Category>(`catalog/categories/${id}/`, data);
        return response.data;
    },
    deleteCategory: async (id: number): Promise<void> => {
        await apiClient.delete(`catalog/categories/${id}/`);
    },
    getOffers: async (params?: { product?: number; supplier?: number; fetchAll?: boolean }): Promise<SupplierOffer[]> => {
        let url = 'catalog/offers/';
        if (params) {
            const query = new URLSearchParams();
            if (params.product) query.append('product', String(params.product));
            if (params.supplier) query.append('supplier', String(params.supplier));
            if (query.toString()) url += `?${query.toString()}`;
        }
        if (params?.fetchAll) return fetchAllPages<SupplierOffer>(url);
        const response = await apiClient.get<PaginatedResponse<SupplierOffer>>(url);
        return response.data.results;
    },
    createOffer: async (data: Partial<SupplierOffer>): Promise<SupplierOffer> => {
        const response = await apiClient.post<SupplierOffer>('catalog/offers/', data);
        return response.data;
    },
    updateOffer: async (id: number, data: Partial<SupplierOffer>): Promise<SupplierOffer> => {
        const response = await apiClient.patch<SupplierOffer>(`catalog/offers/${id}/`, data);
        return response.data;
    },
    deleteOffer: async (id: number): Promise<void> => {
        await apiClient.delete(`catalog/offers/${id}/`);
    },
    bulkPublishProducts: async (ids: number[]): Promise<{ message: string }> => {
        const response = await apiClient.post<{ message: string }>('catalog/products/bulk_publish/', { product_ids: ids });
        return response.data;
    },
    getProductStatuses: async (): Promise<ProductStatusItem[]> => {
        const response = await apiClient.get<ProductStatusItem[]>('catalog/product-statuses/');
        return response.data;
    },
    getStockStatuses: async (): Promise<ProductStatusItem[]> => {
        const response = await apiClient.get<ProductStatusItem[]>('catalog/stock-statuses/');
        return response.data;
    },
    uploadProductImage: async (
        productId: number,
        file: File,
        opts?: { is_main?: boolean; alt_text?: string },
    ): Promise<ProductImage> => {
        const formData = new FormData();
        formData.append('image', file);
        if (opts?.is_main) formData.append('is_main', 'true');
        if (opts?.alt_text) formData.append('alt_text', opts.alt_text);
        const response = await apiClient.post<ProductImage>(
            `catalog/products/${productId}/upload-image/`,
            formData,
            { headers: { 'Content-Type': 'multipart/form-data' } },
        );
        return response.data;
    },
    deleteProductImage: async (productId: number, imageId: number): Promise<void> => {
        await apiClient.delete(`catalog/products/${productId}/delete-image/${imageId}/`);
    },
    uploadProductDocument: async (
        productId: number,
        file: File,
        name?: string,
    ): Promise<ProductDocument> => {
        const formData = new FormData();
        formData.append('file', file);
        if (name) formData.append('name', name);
        const response = await apiClient.post<ProductDocument>(
            `catalog/products/${productId}/upload-document/`,
            formData,
            { headers: { 'Content-Type': 'multipart/form-data' } },
        );
        return response.data;
    },
    deleteProductDocument: async (productId: number, docId: number): Promise<void> => {
        await apiClient.delete(`catalog/products/${productId}/delete-document/${docId}/`);
    },
    // AI #2: draft description / specs / category-hint from a product name (+ optional
    // MPN / ГОСТ / domain). SUGGESTION ONLY — the seller reviews & edits before saving.
    // Returns an empty suggestion ({}) when AI is disabled server-side.
    // ARCH-01: 202 + task_id, resolved via the ai-status poll (same return shape).
    enrichProduct: async (params: {
        name: string;
        domain_code?: string;
        mpn?: string;
        gost?: string;
    }): Promise<ProductEnrichSuggestion> => {
        const result = await runAiJob<{ suggestion: ProductEnrichSuggestion }>(async () => {
            const response = await apiClient.post<{ task_id: string }>(
                'catalog/product-enrich/',
                params,
            );
            return response.data;
        });
        return result.suggestion ?? {};
    },
};

export interface ProductEnrichSuggestion {
    description?: string;
    specifications?: { key: string; value: string }[];
    /** Текстовая подсказка — запасной вариант, когда ни один кандидат-категория не подошёл. */
    suggested_category_hint?: string;
    /**
     * Код ТН ВЭД, ВЫБРАННЫЙ из справочника и детерминированно сверенный сервером
     * (`""` — не подошёл ни один). Раньше сервер его считал, а клиент даже не объявлял:
     * продавец платил за обогащение, кода не видел и жал вторую платную кнопку.
     */
    hs_code?: string;
    hs_candidates?: { code: string; name: string; level: number; score: number }[];
    /** id категории ИЗ справочника (`null` — не подошла ни одна). Выдумать id сервер не даёт. */
    category_id?: number | null;
    /** Код единицы измерения из справочника UN/ECE (`""` — не подошла ни одна). */
    uom_code?: string;
}

export interface ProductImage {
    id: number;
    image: string | null;
    image_url: string | null;
    is_main: boolean;
    alt_text?: string;
}

export interface ProductDocument {
    id: number;
    file: string | null;
    file_url: string | null;
    name: string;
    uploaded_at?: string;
}
