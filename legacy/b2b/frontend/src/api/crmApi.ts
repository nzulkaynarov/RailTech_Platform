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
	status_code: string;
	status_name: string;
	tax_country?: number | null;
	vat_rate?: string;
	items: QuoteItem[];
	subtotal_excl_vat: string;
	vat_amount: string;
	total_incl_vat: string;
	valid_until?: string | null;
	notes?: string;
	pdf_file?: string | null;
	frozen_at?: string | null;
	approved_by?: number | null;
	approved_at?: string | null;
	created_at: string;
	updated_at?: string;
}

export interface Message {
	id: number;
	deal: number;
	sender: number;
	sender_name: string;
	text: string;
	message_type?: string;
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
	manager_name?: string;
	stage?: number | null;
	stage_code?: string;
	stage_name?: string;
	title?: string;
	total_value?: string;
	notes?: string;
	active_quote?: Quote | null;
	quotes?: Quote[];
	created_at: string;
	updated_at?: string;
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
	id?: number;
	name: string;
	company?: string;
	phone: string;
	email: string;
	message?: string;
	is_processed?: boolean;
	created_at?: string;
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
	forceChangeDealStage: async (dealId: number, stageCode: string, reason?: string) => {
		const response = await apiClient.post<Deal>(
			`crm/deals/${dealId}/force-change-stage/`,
			{ stage_code: stageCode, reason: reason || '' },
		);
		return response.data;
	},
	deleteDeal: async (id: number) => {
		await apiClient.delete(`crm/deals/${id}/`);
	},
	getDealStages: async () => {
		const response = await apiClient.get<{ code: string; name: string }[]>('crm/deal-stages/');
		return response.data;
	},
	getQuoteStatuses: async () => {
		const response = await apiClient.get<{ code: string; name: string }[]>('crm/quote-statuses/');
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
	getRecentMessages: async () => {
		const response = await apiClient.get<PaginatedResponse<Message>>('crm/messages/?ordering=-timestamp&page_size=20');
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
		const response = await apiClient.get(`crm/deals/${dealId}/export-pdf/`, {
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
	},
	getQuotes: async () => {
		const response = await apiClient.get<PaginatedResponse<Quote>>('crm/quotes/');
		return response.data.results;
	},
	getQuote: async (id: number) => {
		const response = await apiClient.get<Quote>(`crm/quotes/${id}/`);
		return response.data;
	},
	createQuote: async (data: { deal: number; notes?: string; valid_until?: string }) => {
		const response = await apiClient.post<Quote>('crm/quotes/', data);
		return response.data;
	},
	generateQuotePDF: async (id: number) => {
		const response = await apiClient.post<{ url: string }>(`crm/quotes/${id}/generate-pdf/`);
		return response.data;
	},
	sendQuoteToClient: async (id: number) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/send-to-client/`);
		return response.data;
	},
	approveQuote: async (id: number) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/approve/`);
		return response.data;
	},
	rejectQuote: async (id: number, reason = '') => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/reject/`, { reason });
		return response.data;
	},
	forceApproveQuote: async (id: number, reason: string) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/force-approve/`, { reason });
		return response.data;
	},

	// ─── КП internal approval chain (документооборот) ─────────
	// DRAFT → PENDING_TRADE_REVIEW → PENDING_APPROVAL → READY_TO_SEND.
	// Role gating lives in the backend service (anchored to the КП's owning
	// company); a forbidden role returns { error: 'ROLE_NOT_PERMITTED' } → 403.
	submitQuoteForReview: async (id: number) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/submit-for-review/`);
		return response.data;
	},
	confirmQuoteTradeReview: async (id: number) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/confirm-trade-review/`);
		return response.data;
	},
	directorApproveQuote: async (id: number) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/director-approve/`);
		return response.data;
	},
	sendQuoteBack: async (id: number, reason: string) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/send-back/`, { reason });
		return response.data;
	},
	getMyApprovalQueue: async () => {
		const response = await apiClient.get<PaginatedResponse<Quote>>('crm/quotes/my-approval-queue/');
		return response.data.results;
	},
	downloadQuotePDF: async (id: number) => {
		const response = await apiClient.get(`crm/quotes/${id}/download-pdf/`, {
			responseType: 'blob'
		});
		const url = window.URL.createObjectURL(new Blob([response.data]));
		const link = document.createElement('a');
		link.href = url;
		link.setAttribute('download', `RailTech_Quote_${id}.pdf`);
		document.body.appendChild(link);
		link.click();
		link.remove();
	},

	// ─── Lead ops ─────────────────────────────────────────────
	listLeads: async () => {
		const response = await apiClient.get<PaginatedResponse<Lead>>('crm/leads/');
		return response.data.results;
	},
	convertLead: async (leadId: number, companyId?: number) => {
		const response = await apiClient.post<{ deal_id: number; stage: string }>(
			`crm/leads/${leadId}/convert/`,
			companyId ? { company_id: companyId } : {},
		);
		return response.data;
	},

	// ─── Quote item re-match ─────────────────────────────────
	matchCandidates: async (quoteItemId: number) => {
		const response = await apiClient.get<{
			raw: string;
			candidates: Array<{ product_id: number; sku: string; name: string; gost: string; score: number }>;
		}>(`crm/quote-items/${quoteItemId}/match-candidates/`);
		return response.data;
	},
	reassignProduct: async (quoteItemId: number, productId: number | null) => {
		const response = await apiClient.post<QuoteItem>(
			`crm/quote-items/${quoteItemId}/reassign-product/`,
			{ product_id: productId },
		);
		return response.data;
	},
};

