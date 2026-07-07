import { runAiJob } from '@/lib/aiJob';
import { apiClient } from './client';
import { PaginatedResponse } from './types';

export interface DomainTypeItem {
    id: number;
    code: string;
    name: string;
    sku_prefix: string;
    sort_order: number;
    is_active: boolean;
}

export interface EquipmentGroup {
    id: number;
    name: string;
    full_path: string;
    parent?: number | null;
    description?: string;
    sort_order?: number;
    is_active?: boolean;
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
    name: string;
    country: string;
    is_verified?: boolean;
    has_iso9001?: boolean;
    trust_score?: number;
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
    
    manufacturer?: number | null;

    // The SELLER company that owns the listing (tenancy), NOT the OEM.
    owner_company_data?: { id: number; name: string; inn?: string; logo?: string | null } | null;

    // Canonical brand (catalog.Manufacturer / OEM). This is what catalog
    // displays show as "manufacturer/производитель".
    brand?: number | null;
    brand_name?: string | null;
    brand_country?: string | null;
    manufacturer_part_number?: string | null;

    uom?: number | null;
    uom_data?: { id: number; code: string; name: string } | null;

    stock_status?: string | null;
    base_price: string;

    gost_drawing?: string | null;
    specifications?: {
        tech_specs?: string;
        [key: string]: string | number | boolean | null | undefined;
    } | null;
    
    images?: { id: number, image: string | null, image_url: string | null, is_main: boolean }[];
    documents?: { id: number, file: string | null, file_url: string | null, name: string }[];
    
    main_image_url?: string | null;
    main_document_url?: string | null;
    
    equipment_groups?: EquipmentGroup[];
    offers?: SupplierOffer[];
    created_at?: string;
    updated_at?: string;
}

// DRF's default PageNumberPagination caps every list at PAGE_SIZE (20) and ignores
// a client `page_size`/`limit` override. Admin list pages do their own client-side
// search/sort/pagination, so they need the COMPLETE set, not the first 20 rows.
// This walks the `next` links and concatenates every page (H4 fix). Public/seller
// surfaces keep the single-page fetch — they opt in via `fetchAll`.
async function fetchAllPages<T>(firstUrl: string): Promise<T[]> {
    const all: T[] = [];
    let nextUrl: string | null = firstUrl;
    // Hard ceiling so a runaway `next` chain can't loop forever.
    let guard = 0;
    while (nextUrl && guard < 500) {
        // Fresh const per iteration — keeps the request argument out of the
        // reassignment cycle (`nextUrl` ← next ← data ← nextUrl) that confuses
        // TS control-flow inference (TS7022).
        const currentUrl: string = nextUrl;
        const resp = await apiClient.get<PaginatedResponse<T>>(currentUrl);
        all.push(...resp.data.results);
        // `next` is an absolute URL; apiClient baseURL already targets the API root,
        // so strip everything up to and including `/api/v1/` to get a relative path.
        const rawNext: string | null = resp.data.next;
        nextUrl = rawNext ? rawNext.replace(/^.*\/api\/v1\//, '') : null;
        guard += 1;
    }
    return all;
}

export const catalogApi = {
    getDomainTypes: async (): Promise<DomainTypeItem[]> => {
        const response = await apiClient.get<DomainTypeItem[]>('catalog/domain-types/');
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
    getEquipmentGroups: async (search?: string, opts?: { fetchAll?: boolean }): Promise<EquipmentGroup[]> => {
        let url = 'catalog/equipment-groups/';
        if (search) {
            url += `?search=${encodeURIComponent(search)}`;
        }
        if (opts?.fetchAll) return fetchAllPages<EquipmentGroup>(url);
        const response = await apiClient.get<PaginatedResponse<EquipmentGroup>>(url);
        return response.data.results;
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
    createEquipmentGroup: async (data: Partial<EquipmentGroup>): Promise<EquipmentGroup> => {
        const response = await apiClient.post<EquipmentGroup>('catalog/equipment-groups/', data);
        return response.data;
    },
    updateEquipmentGroup: async (id: number, data: Partial<EquipmentGroup>): Promise<EquipmentGroup> => {
        const response = await apiClient.patch<EquipmentGroup>(`catalog/equipment-groups/${id}/`, data);
        return response.data;
    },
    deleteEquipmentGroup: async (id: number): Promise<void> => {
        await apiClient.delete(`catalog/equipment-groups/${id}/`);
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
    suggested_category_hint?: string;
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
