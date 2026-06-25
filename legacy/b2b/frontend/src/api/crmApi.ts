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
	unit?: string;
	unit_code?: string;
	mpn?: string;
	gost_drawing?: string;
	hs_code?: string;
	note?: string;
	is_incomplete?: boolean;
	frozen_base_price: string;
	frozen_currency: string;
	logistics_cost: string;
	customs_duty: string;
	margin_percent: string;
	discount_percent: string;
	landed_cost: string;
	final_price_excl_vat: string;
	assigned_at?: string | null;
}

export type DealItem = QuoteItem;

// ─── AI catalog match (sourcing/match-catalog) ───────────────────────────
// A single catalog product proposed for an unmatched КП line.
export interface CatalogCandidate {
	product_id: number;
	name: string;
	sku: string;
	confidence: number; // 0..1
	reason: string;
}

// Candidates for one POSTed line. `line_index` is the index into the `lines`
// array sent in the request (NOT the QuoteItem id) — caller maps it back.
export interface CatalogMatch {
	line_index: number;
	candidates: CatalogCandidate[];
}

export interface MatchCatalogLine {
	name: string;
	mpn?: string;
	gost_drawing?: string;
}

export interface MatchCatalogPayload {
	lines: MatchCatalogLine[];
	domain_code?: string;
	top_k?: number;
}

// AI #7 pre-flight quality check — one advisory finding per flagged line.
// line_index references a line in the sent array (NOT a QuoteItem id).
export interface PreflightFinding {
	line_index: number;
	severity: 'info' | 'warning';
	issue: string;
	suggestion: string;
}

export interface PreflightLine {
	name: string;
	quantity?: number;
	unit?: string;
	mpn?: string;
	gost_drawing?: string;
	note?: string;
}

export interface PreflightPayload {
	lines: PreflightLine[];
	domain_code?: string;
}

// Incoterms 2020 cost-responsibility flags — drive which cost rows the КП builder
// shows / requires for the selected delivery basis (code reads flags, no hardcode).
export interface DeliveryBasis {
	id: number;
	code: string;
	name: string;
	description?: string;
	seller_pays_freight: boolean;
	seller_pays_insurance: boolean;
	seller_pays_import: boolean;
	seller_pays_delivery: boolean;
}

// КП-level expense item / discount (UBL document AllowanceCharge). Seller-only —
// the buyer never receives these rows (server gates them).
export interface QuoteCharge {
	id: number;
	quote: number;
	charge_type: string;          // ChargeType code, e.g. 'FREIGHT'
	charge_type_name?: string;
	description?: string;
	amount: string;
	rate_percent?: string | null; // % of subtotal; takes priority over amount
	is_deduction: boolean;        // true = discount (−), false = charge (+)
	created_by?: number | null;
	created_at?: string;
}

// Per-company charge template (org-admin): default charges auto-applied per basis.
export interface ChargeTemplate {
	id: number;
	delivery_basis: string;        // Incoterm code
	delivery_basis_name?: string;
	charge_type: string;           // ChargeType code
	charge_type_name?: string;
	default_amount: string;
	default_rate_percent?: string | null;
	is_deduction: boolean;
	sort_order: number;
	is_active: boolean;
}

export interface Quote {
	id: number;
	deal: number;
	version: number;
	status: number;
	status_code: string;
	status_name: string;
	delivery_basis?: number | null;
	delivery_basis_data?: DeliveryBasis | null;
	quote_currency?: string | null;
	tax_country?: number | null;
	vat_rate?: string;
	items: QuoteItem[];
	charges?: QuoteCharge[];       // seller-only; absent for buyers
	subtotal_excl_vat: string;
	charges_total?: string;        // seller-only
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

// A seller company an RFQ is routed to (multi-seller routing). Minimal shape —
// id + display name — used both for the routing picker and the "Routed to" line.
export interface SellerCompanyRef {
	id: number;
	name: string;
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
	can_edit_request?: boolean;
	// Seller companies this RFQ is routed to (read-only; populated by routeDeal).
	target_sellers_data?: SellerCompanyRef[];
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
	// Buyer adds a row to their own request (name + qty). Creates the underlying
	// DRAFT quote on first add; allowed only while the seller hasn't engaged.
	addRequestItem: async (dealId: number, data: { name: string; quantity: number; unit?: string; unit_code?: string; note?: string; mpn?: string }) => {
		const response = await apiClient.post<QuoteItem>(`crm/deals/${dealId}/add-request-item/`, data);
		return response.data;
	},
	// Buyer edits the request header (title + note to seller) while DRAFT.
	updateRequestMeta: async (dealId: number, data: { title?: string; notes?: string }) => {
		const response = await apiClient.patch<Deal>(`crm/deals/${dealId}/update-request-meta/`, data);
		return response.data;
	},
	// Buyer adds a batch of request lines at once (catalog cart checkout).
	addRequestItems: async (dealId: number, items: { product_id?: number; name?: string; quantity: number }[]) => {
		const response = await apiClient.post<QuoteItem[]>(`crm/deals/${dealId}/add-request-items/`, { items });
		return response.data;
	},
	// Buyer issues the RFQ to the seller (Draft → RFQ_OPEN). The «Отправить заявку» step.
	submitRequest: async (dealId: number) => {
		const response = await apiClient.post<Deal>(`crm/deals/${dealId}/submit-request/`);
		return response.data;
	},
	// ─── Multi-seller routing ────────────────────────────────────────────────
	// Active SUPPLIER companies — the buyer's routing picker source. The endpoint
	// may be paginated or return a bare array; unwrap both shapes.
	getDealSuppliers: async (): Promise<SellerCompanyRef[]> => {
		const response = await apiClient.get<SellerCompanyRef[] | PaginatedResponse<SellerCompanyRef>>('crm/deals/suppliers/');
		const { data } = response;
		return Array.isArray(data) ? data : data.results;
	},
	// Buyer routes a DRAFT RFQ to one or more seller companies (by company id).
	// Returns the refreshed deal (incl. target_sellers_data).
	routeDeal: async (dealId: number, sellerCompanyIds: number[]) => {
		const response = await apiClient.post<Deal>(`crm/deals/${dealId}/route/`, { seller_company_ids: sellerCompanyIds });
		return response.data;
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
	getChargeTypes: async () => {
		const response = await apiClient.get<{ id: number; code: string; name: string }[]>('crm/charge-types/');
		return response.data;
	},
	// ─── Org-admin: the company's per-Incoterm charge templates ───
	getChargeTemplates: async () => {
		const response = await apiClient.get<ChargeTemplate[]>('crm/charge-templates/');
		return response.data;
	},
	createChargeTemplate: async (data: {
		delivery_basis: string; charge_type: string;
		default_amount?: string; default_rate_percent?: string | null; is_deduction?: boolean; sort_order?: number;
	}) => {
		const response = await apiClient.post<ChargeTemplate>('crm/charge-templates/', data);
		return response.data;
	},
	deleteChargeTemplate: async (id: number) => {
		await apiClient.delete(`crm/charge-templates/${id}/`);
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
	importExcelToDeal: async (dealId: number, file: File, useAI = false) => {
		const formData = new FormData();
		formData.append('file', file);
		if (useAI) formData.append('use_ai', 'true');
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
	// Seller sets КП-level fields (currency, notes, validity).
	updateQuote: async (id: number, data: Partial<Pick<Quote, 'quote_currency' | 'notes' | 'valid_until'>>) => {
		const response = await apiClient.patch<Quote>(`crm/quotes/${id}/`, data);
		return response.data;
	},
	// Seller picks the Incoterm → server sets the basis AND auto-applies its charge
	// template (the default expense items for that basis). Dedicated endpoint, not a
	// plain PATCH, so the template side-effect is explicit.
	setQuoteDeliveryBasis: async (id: number, deliveryBasis: number) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/set-delivery-basis/`, { delivery_basis: deliveryBasis });
		return response.data;
	},
	// ─── КП-level expense items / discounts (UBL document AllowanceCharge) ───
	getQuoteCharges: async (quoteId: number) => {
		const response = await apiClient.get<PaginatedResponse<QuoteCharge>>(`crm/quote-charges/?quote=${quoteId}`);
		return response.data.results;
	},
	createQuoteCharge: async (data: { quote: number; charge_type: string; description?: string; amount?: string; rate_percent?: string | null; is_deduction?: boolean }) => {
		const response = await apiClient.post<QuoteCharge>('crm/quote-charges/', data);
		return response.data;
	},
	updateQuoteCharge: async (id: number, data: Partial<QuoteCharge>) => {
		const response = await apiClient.patch<QuoteCharge>(`crm/quote-charges/${id}/`, data);
		return response.data;
	},
	deleteQuoteCharge: async (id: number) => {
		await apiClient.delete(`crm/quote-charges/${id}/`);
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

	// ─── AI catalog match ────────────────────────────────────
	// POST a batch of unmatched lines → candidate catalog products per line.
	// Only lines with ≥1 candidate are returned; may 503 {error:'AI_DISABLED'}.
	matchCatalog: async (payload: MatchCatalogPayload) => {
		const response = await apiClient.post<{ matches: CatalogMatch[] }>(
			'sourcing/match-catalog/',
			payload,
		);
		return response.data;
	},

	// ─── AI #7 pre-flight quality check ──────────────────────
	// POST draft request lines → advisory quality findings per line.
	// Advisory only (never blocks submit); may 503 {error:'AI_DISABLED'}.
	preflightCheck: async (payload: PreflightPayload) => {
		const response = await apiClient.post<{ findings: PreflightFinding[] }>(
			'sourcing/preflight-check/',
			payload,
		);
		return response.data;
	},
};

