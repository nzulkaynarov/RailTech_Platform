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
}

export interface Category {
    id: number;
    name: string;
    parent?: number | null;
    domain_type?: number | null;
    icon?: string | null;
}

export interface Manufacturer {
    id: number;
    name: string;
    country: string;
}

export interface SupplierOffer {
    id: number;
    supplier: number;
    supplier_data?: { id: number; name: string } | null;
    supplier_sku?: string;
    base_price: string;
    currency?: number | null;
    currency_data?: { id: number; code: string; symbol: string } | null;
    delivery_basis?: number | null;
    delivery_basis_data?: { id: number; code: string; name: string } | null;
    stock_status?: string | null;
    delivery_lead_time?: string;
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
    domain_type: number | string;
    domain_type_name: string;
    domain_type_code?: string;
    
    category?: number | null;
    category_data?: { id: number, name: string } | null;
    
    manufacturer?: number | null;
    manufacturer_data?: { id: number; name: string; inn?: string; logo?: string | null } | null;

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

export const catalogApi = {
    getDomainTypes: async (): Promise<DomainTypeItem[]> => {
        const response = await apiClient.get<DomainTypeItem[]>('catalog/domain-types/');
        return response.data;
    },

    getProducts: async (params?: {
        domain_type?: string,
        search?: string,
        category?: number,
        manufacturer?: number,
        equipment_groups?: number,
        stock_status?: string,
    }): Promise<Product[]> => {
        let url = 'catalog/products/';
        if (params) {
            const query = new URLSearchParams();
            if (params.domain_type) query.append('domain_type__code', params.domain_type);
            if (params.search) query.append('search', params.search);
            if (params.category) query.append('category', params.category.toString());
            if (params.manufacturer) query.append('manufacturer', params.manufacturer.toString());
            if (params.equipment_groups) query.append('equipment_groups', params.equipment_groups.toString());
            if (params.stock_status) query.append('stock_status', params.stock_status);
            if (query.toString()) url += `?${query.toString()}`;
        }
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
    getCategories: async (params?: { domain_type?: string }): Promise<Category[]> => {
        let url = 'catalog/categories/';
        if (params?.domain_type) {
            url += `?domain_type__code=${params.domain_type}`;
        }
        const response = await apiClient.get<PaginatedResponse<Category>>(url);
        return response.data.results;
    },
    getManufacturers: async (): Promise<Manufacturer[]> => {
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
    getEquipmentGroups: async (search?: string): Promise<EquipmentGroup[]> => {
        let url = 'catalog/equipment-groups/';
        if (search) {
            url += `?search=${encodeURIComponent(search)}`;
        }
        const response = await apiClient.get<PaginatedResponse<EquipmentGroup>>(url);
        return response.data.results;
    },
    importExcel: async (file: File): Promise<{ task_id: string }> => {
        const formData = new FormData();
        formData.append('file', file);
        const response = await apiClient.post('sourcing/import-catalog/', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
        return response.data;
    },
    exportTemplate: async (): Promise<void> => {
        const response = await apiClient.get('catalog/products/export-template/', {
            responseType: 'blob'
        });
        const url = window.URL.createObjectURL(new Blob([response.data]));
        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', 'railtech_catalog_template.xlsx');
        document.body.appendChild(link);
        link.click();
        link.remove();
    }
};
