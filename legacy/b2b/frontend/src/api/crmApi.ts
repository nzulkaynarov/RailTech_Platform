import { apiClient } from './client';
import { Product as CatalogProduct } from './catalogApi';
import { PaginatedResponse } from './types';

export type Product = CatalogProduct;

export interface QuoteItem {
	id: number;
	quote: number;
	product?: number | null;
	product_name?: string;
	product_domain?: string;
	product_sku?: string;
	product_gost?: string;
	offer?: number | null;
	offer_supplier_name?: string;
	imported_raw_name: string;
	quantity: number;
	frozen_base_price: string;
	frozen_currency: string;
	logistics_cost: string;
	customs_duty: string;
	margin_percent: string;
	landed_cost: string;
	final_price_excl_vat: string;
	assigned_at?: string | null;
}

export type DealItem = QuoteItem;

export interface Quote {
	id: number;
	deal: number;
	version: number;
	status: number;
	status_name: string;
	tax_country?: number | null;
	vat_rate?: string;
	items: QuoteItem[];
	subtotal_excl_vat: string;
	vat_amount: string;
	total_incl_vat: string;
	valid_until?: string | null;
	notes?: string;
	created_at: string;
}

export interface Message {
	id: number;
	deal: number;
	sender: number;
	sender_name: string;
	text: string;
	timestamp: string;
	is_me: boolean;
}

export interface Deal {
	id: number;
	company?: number | null;
	company_name?: string;
	client?: number | null;
	client_name?: string;
	manager?: number | null;
	stage?: number | null;
	stage_name?: string;
	title?: string;
	total_value?: string;
	active_quote?: Quote | null;
	quotes?: Quote[];
	created_at: string;
}

export interface CRMAnalytics {
	pipeline_by_status: { stage__name: string, count: number }[];
	sourcing_backlog: number;
	kyc_backlog: number;
	total_pipeline_value: number;
	mapped_items_percentage: number;
	conversion_rate?: number;
	avg_margin?: number;
	sourcing_speed_avg?: number;
}

export interface ActivityLog {
	id: number;
	action: string;
	detail: string;
	user_name: string;
	level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR';
	timestamp: string;
}

export interface Lead {
	name: string;
	company?: string;
	phone: string;
	email: string;
	message?: string;
}

export const crmApi = {
	getDeals: async () => {
		const response = await apiClient.get<PaginatedResponse<Deal>>('crm/deals/');
		return response.data.results;
	},
	getDeal: async (id: number) => {
		const response = await apiClient.get<Deal>(`crm/deals/${id}/`);
		return response.data;
	},
	createDeal: async (data: { title?: string; notes?: string }) => {
		const response = await apiClient.post<Deal>('crm/deals/', data);
		return response.data;
	},
	updateDeal: async (id: number, data: Partial<Deal>) => {
		const response = await apiClient.patch<Deal>(`crm/deals/${id}/`, data);
		return response.data;
	},
	createQuoteItem: async (data: { quote: number; imported_raw_name: string; quantity: number; frozen_base_price?: string; frozen_currency?: string }) => {
		const response = await apiClient.post<QuoteItem>('crm/quote-items/', data);
		return response.data;
	},
	deleteQuoteItem: async (id: number) => {
		await apiClient.delete(`crm/quote-items/${id}/`);
	},
	changeDealStage: async (dealId: number, stageCode: string) => {
		const response = await apiClient.post<Deal>(`crm/deals/${dealId}/change-stage/`, { stage_code: stageCode });
		return response.data;
	},
	getQuoteItems: async (params?: { deal_id?: number, product_is_null?: boolean }) => {
		let url = 'crm/quote-items/';
		if (params) {
			const query = new URLSearchParams();
			if (params.deal_id) query.append('deal_id', params.deal_id.toString());
			if (params.product_is_null) query.append('product__isnull', 'true');
			if (query.toString()) url += `?${query.toString()}`;
		}
		const response = await apiClient.get<PaginatedResponse<QuoteItem>>(url);
		return response.data.results;
	},
	updateQuoteItem: async (id: number, data: Partial<QuoteItem>) => {
		const response = await apiClient.patch<QuoteItem>(`crm/quote-items/${id}/`, data);
		return response.data;
	},
	getProducts: async (search?: string) => {
		let url = 'catalog/products/';
		if (search) {
			url += `?search=${encodeURIComponent(search)}`;
		}
		const response = await apiClient.get<PaginatedResponse<Product>>(url);
		return response.data.results;
	},
	importExcelToDeal: async (dealId: number, file: File) => {
		const formData = new FormData();
		formData.append('file', file);
		const response = await apiClient.post<{ message: string, task_id: string }>(
			`sourcing/import-deal/${dealId}/`,
			formData,
			{
				headers: {
					'Content-Type': 'multipart/form-data',
				},
			}
		);
		return response.data;
	},
	getMessages: async (dealId: number) => {
		const response = await apiClient.get<PaginatedResponse<Message>>(`crm/messages/?deal_id=${dealId}`);
		return response.data.results;
	},
	sendMessage: async (dealId: number, text: string) => {
		const response = await apiClient.post<Message>('crm/messages/', {
			deal: dealId,
			text: text
		});
		return response.data;
	},
	getTaskStatus: async (taskId: string) => {
		const response = await apiClient.get<{
			task_id: string;
			status: string;
			result: unknown;
			meta?: { current: number; total: number };
		}>(`sourcing/import-status/${taskId}/`);
		return response.data;
	},
	exportDealPDF: async (dealId: number) => {
		const response = await apiClient.get(`crm/deals/${dealId}/export_pdf/`, {
			responseType: 'blob'
		});
		const url = window.URL.createObjectURL(new Blob([response.data]));
		const link = document.createElement('a');
		link.href = url;
		link.setAttribute('download', `RailTech_Quote_${dealId}.pdf`);
		document.body.appendChild(link);
		link.click();
		link.remove();
	},
	getAnalytics: async () => {
		const response = await apiClient.get<CRMAnalytics>('crm/analytics/');
		return response.data;
	},
	getActivityLogs: async () => {
		const response = await apiClient.get<PaginatedResponse<ActivityLog>>('crm/activity-logs/');
		return response.data.results;
	},
	submitLead: async (data: Lead) => {
		const response = await apiClient.post<Lead>('crm/leads/', data);
		return response.data;
	}
};
