import { runAiJob } from '@/lib/aiJob';
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
	product_mpn?: string;
	product_uom?: string;
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
	// The LINE's COST currency (base-price currency), code e.g. "USD". null ⇒ UZS.
	frozen_currency: string;
	logistics_cost: string;
	// customs_duty is entered in the SAME line currency as frozen_base_price.
	customs_duty: string;
	margin_percent: string;
	discount_percent: string;
	// Per-line срок поставки (days). КП-level effective срок = max over lines.
	lead_time_days: number;
	// landed_cost / final_price_excl_vat are READ-ONLY and now in UZS
	// = (frozen_base_price + customs_duty) × fx rate of frozen_currency.
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

// ─── Pricing-assist (Move 3): suggested line cost from the seller's SupplierOffer ─────────
export interface PricingSuggestion {
	item_id: number;
	product_id: number;
	base_price: string;
	currency: string | null;
	lead_time_days: number;
	supplier_sku?: string;
	delivery_basis?: string | null;
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

// AI #3 — «КП vs заявка» coverage / discrepancy check (advisory, never blocks).
// issue_type is a CODE (compare by code, not translated text). `line` is the
// 0-based index into the КП's items, resolvable back to requested/quoted names.
export type QuoteDiffIssueType =
	| 'uncovered' // seller did not price this requested line
	| 'substituted' // a non-equivalent catalog product was offered
	| 'note_ignored' // the line's note/requirement may have been ignored
	| 'qty_unit'; // quantity / unit mismatch (reserved)

export interface QuoteDiffFinding {
	issue_type: QuoteDiffIssueType;
	line: number;
	explanation: string;
}

export interface QuoteDiffResult {
	ai_enabled: boolean;
	findings: QuoteDiffFinding[];
}

// AI #6 — signed contract / counter-invoice extraction + code-side reconciliation.
// The model TRANSCRIBES these fields (untrusted OCR); the money verdict in `comparison`
// is recomputed on the backend in Decimal. line_index/totals are strings as read.
export interface DocExtractLineTotal {
	description: string;
	line_total: string;
}

export interface DocExtractedFields {
	total: string;
	currency_code: string;
	valid_until: string;
	bank_details: string;
	line_totals: DocExtractLineTotal[];
}

// Stable machine codes for each reconciliation flag (compared by code, never name).
export type DocMismatchCode =
	| 'TOTAL_MISMATCH'
	| 'CURRENCY_UNKNOWN'
	| 'FOREIGN_CURRENCY'
	| 'DOCUMENT_EXPIRED'
	| 'TOTAL_NOT_FOUND'
	| 'CURRENCY_NOT_FOUND';

export interface DocMismatch {
	code: DocMismatchCode;
	document_total?: string;
	expected_total?: string;
	difference?: string;
	document_currency?: string;
	expected_currency?: string;
	valid_until?: string;
}

export interface DocComparison {
	ok: boolean;
	mismatches: DocMismatch[];
	parsed: {
		document_total: string | null;
		document_currency: string | null;
		valid_until: string | null;
		bank_details: string | null;
		line_count: number;
	};
}

export interface DocCheckResult {
	reference: { kind: 'quote' | 'contract'; id: number };
	extracted: DocExtractedFields;
	comparison: DocComparison;
}

export interface DocCheckPayload {
	file: File;
	quoteId?: number;
	contractId?: number;
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
	cost_amount?: string | null;  // seller's REAL cost (null ⇒ billed-at-cost pass-through)
	is_deduction: boolean;        // true = discount (−), false = charge (+)
	from_template?: boolean;      // auto-created from an Incoterm template (vs added by hand)
	sort_order?: number;          // cascade position (top→bottom); reorder changes the % base
	resolved_base?: string | null;   // running tax-excl subtotal this row was applied to
	resolved_amount?: string | null; // signed computed amount (UBL BaseAmount/Amount)
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

/** Seller unit economics for the КП (cost-gated; null when the viewer can't see costs or
 *  on list endpoints). Decimals arrive as strings. */
export interface QuoteEconomics {
	total_landed_cost: string;
	gross_profit: string;
	gross_margin_percent: string;   // gross margin ON PRICE (governance metric)
	markup_percent: string;         // markup on cost (reference)
	charge_cost_total: string;
	operating_profit: string;
	below_cost: boolean;            // hard-stop flag: operating profit < 0 (landed + charge costs)
	below_floor: boolean;           // warn+approval flag: margin < company floor
	min_margin_percent: string;
	target_margin_percent: string;
	fx_missing: string[];           // line currencies with NO resolvable rate → blocks submit/send
}

/** One node of the КП internal approval chain (unified workflow). */
export interface QuoteApprovalStep {
	id: number;
	order: number;
	participation: 'HEAD' | 'APPROVER' | 'INFORMED';
	status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'SKIPPED' | 'RECALLED';
	approver: number | null;
	approver_name: string;
	approver_role: number | null;
	acted_by: number | null;
	acted_by_name: string;
	is_mandatory: boolean;
	is_auto: boolean;
	trigger_reason: string;
	comment: string;
	decided_at: string | null;
	created_at: string;
	can_act: boolean;        // may the requesting user act on this step right now
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
	// Presentation currency (all stored totals are in UZS regardless); Currency code.
	quote_currency?: string | null;
	// Default cost currency new lines inherit (Currency code or null ⇒ UZS).
	cost_currency_default?: string | null;
	// Frozen FX (READ-ONLY): { currencyCode: "rateToUzsString" } e.g. {"USD":"12000"}.
	fx_snapshot?: Record<string, string>;
	// КП-level manual FX override (read+WRITE) — wins over snapshot & market.
	fx_manual?: Record<string, string>;
	// КП-level срок поставки OVERRIDE in days (null ⇒ use derived max over lines).
	delivery_lead_time_days?: number | null;
	// READ-ONLY computed срок = override if set else max(items[].lead_time_days) (0 if none).
	effective_delivery_lead_time_days?: number;
	// "в наличии" / "под заказ" nuance (max 255).
	delivery_note?: string;
	tax_country?: number | null;
	vat_rate?: string;
	margin_percent?: string;          // КП-level markup applied to every line (F3.8)
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
	// Seller unit economics — present only on the single-quote/deal detail for a cost-viewer.
	economics?: QuoteEconomics | null;
	// Internal approval chain — present only on the single-quote/deal detail.
	approval_steps?: QuoteApprovalStep[];
	created_at: string;
	updated_at?: string;
}

export interface Message {
	id: number;
	deal: number;
	seller_company?: number | null;   // the private seller lane (audit #4); null = deal-level
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
	assigned_to?: number | null;       // deal owner (claimed); null = unclaimed, in the queue
	assigned_to_name?: string;
	assigned_at?: string | null;       // time-to-first-touch anchor
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

/** Wedge metric — hours from RFQ routed → first КП sent (ADR-0006 Move 4). */
export interface TimeToFirstQuoteStats {
	sample_size: number;
	median_hours: number;
	avg_hours: number;
	p90_hours: number;
	fastest_hours: number;
	slowest_hours: number;
}

export interface ActivityLog {
	id: number;
	action: string;
	detail: string;
	event_code?: string;
	event_params?: Record<string, unknown>;
	user_name: string;
	level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR';
	timestamp: string;
}

// CRM Phase A — counterparty / deal activity timeline entry.
export interface TimelineEntry {
	id: number;
	action: string;
	detail: string;
	// Structured event (spec-timeline-i18n): localized on the client from these when present.
	event_code?: string;
	event_params?: Record<string, unknown>;
	level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR';
	timestamp: string;
	user_name: string;
	entity_type: string;
	entity_id: number | null;
	deal_id: number | null;
	company_id: number | null;
	contact_id: number | null;
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

// ─── CRM Phase B — counterparty relationship book («Книга контрагентов») ──
// Direction/stage/source are stable DB codes (Rule 2: compare by code, translate for display).
export type RelationshipDirection = 'CLIENT' | 'SUPPLIER';
export type RelationshipStage = 'PROSPECT' | 'ACTIVE' | 'DORMANT' | 'LOST';
export type RelationshipSource = 'LEAD' | 'OFFLINE_CREATED' | 'INBOUND_RFQ' | 'SELF_REGISTERED';

/** Account summary embedded in a relationship edge (nested read, flat write pattern). */
export interface RelationshipCounterparty {
	id: number;
	name: string;
	inn: string | null;
	// INN as stated by the book owner for an offline (unregistered) counterparty.
	stated_inn: string;
	is_registered: boolean;
	// The counterparty's primary contact — the CB-invite target (Phase D); null if none.
	primary_contact_id: number | null;
}

export interface Relationship {
	id: number;
	direction: RelationshipDirection;
	stage: RelationshipStage;
	source: RelationshipSource;
	counterparty: RelationshipCounterparty;
	owner_member: number | null;
	owner_member_name: string;
	contacts_count: number;
	first_interaction_at: string | null;
	last_interaction_at: string | null;
	deals_count: number;
	won_count: number;
	// Decimal string — total_incl_vat of won deals, UZS-канон.
	gmv: string;
	created_at: string;
}

/** Contact of a company in the team's own client book. */
export interface Contact {
	id: number;
	company: number;
	company_name: string;
	company_is_registered: boolean;
	name: string;
	email?: string;
	phone?: string;
	position?: string;
	is_primary?: boolean;
	created_at: string;
}

/** «Завести оффлайн-клиента» — company + contact in one step (flat write). */
export interface OfflineClientPayload {
	company_name: string;
	contact_name: string;
	inn?: string;
	email?: string;
	phone?: string;
	position?: string;
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
	createQuoteItem: async (data: { quote: number; imported_raw_name: string; quantity: number; frozen_base_price?: string; frozen_currency?: string; lead_time_days?: number }) => {
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
	// ─── Deal ownership / work-queue (ADR-0006 Move 2) ───────────────────────
	claimDeal: async (dealId: number) => {
		const response = await apiClient.post<Deal>(`crm/deals/${dealId}/claim/`);
		return response.data;
	},
	releaseDeal: async (dealId: number) => {
		const response = await apiClient.post<Deal>(`crm/deals/${dealId}/release/`);
		return response.data;
	},
	// ─── Wedge metric: time-to-first-КП (ADR-0006 Move 4) ─────────────────────
	getTimeToFirstQuote: async (sinceDays = 30) => {
		const response = await apiClient.get<TimeToFirstQuoteStats>('crm/analytics/time-to-first-quote/', {
			params: { since_days: sinceDays },
		});
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
			// Backend filterset key is `quote__deal_id` (QuoteItemViewSet.filterset_fields).
			// Sending `deal_id` was silently IGNORED by DRF → the КП builder loaded the
			// seller's items from ALL deals (opening one deal's КП showed another's lines).
			if (params.deal_id) query.append('quote__deal_id', params.deal_id.toString());
			if (params.product_is_null) query.append('product__isnull', 'true');
			if (query.toString()) url += `?${query.toString()}`;
		}
		// QuoteItemViewSet sets pagination_class=None — the КП grid needs every line
		// (economics are computed over all of them), so DRF returns a bare array, not
		// a paginated {count,results} envelope.
		const response = await apiClient.get<QuoteItem[]>(url);
		return response.data;
	},
	updateQuoteItem: async (id: number, data: Partial<QuoteItem>) => {
		const response = await apiClient.patch<QuoteItem>(`crm/quote-items/${id}/`, data);
		return response.data;
	},
	// Transactional bulk save of the edited КП lines (P0-4): ONE request, ONE recalc.
	// All-or-nothing — a rejected batch returns 400 {detail:'QUOTE_ITEMS_BULK_INVALID', rows:[…]}
	// with per-row machine codes and writes nothing (parseBulkItemErrors flattens `rows`).
	bulkUpdateQuoteItems: async (quoteId: number, items: Array<Partial<QuoteItem> & { id: number }>) => {
		const response = await apiClient.post<QuoteItem[]>('crm/quote-items/bulk-update/', {
			quote: quoteId,
			items,
		});
		return response.data;
	},
	// Transactional bulk create of new КП lines (WP-J duplicate / Excel-paste): ONE request, ONE
	// recalc. All-or-nothing — a rejected batch returns 400 {detail:'QUOTE_ITEMS_BULK_INVALID',
	// rows:[…]} keyed by index (new rows carry no id yet) and writes nothing.
	bulkCreateQuoteItems: async (quoteId: number, items: Array<Record<string, unknown>>) => {
		const response = await apiClient.post<QuoteItem[]>('crm/quote-items/bulk-create/', {
			quote: quoteId,
			items,
		});
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
	// sellerCompany = the private lane (which routed seller's thread). A seller omits it —
	// the backend scopes to its own lane; a buyer on a multi-seller deal must pass it (audit #4).
	getMessages: async (dealId: number, sellerCompany?: number | null) => {
		const laneQ = sellerCompany != null ? `&seller_company=${sellerCompany}` : '';
		const response = await apiClient.get<PaginatedResponse<Message>>(`crm/messages/?deal_id=${dealId}${laneQ}`);
		return response.data.results;
	},
	getRecentMessages: async () => {
		const response = await apiClient.get<PaginatedResponse<Message>>('crm/messages/?ordering=-timestamp&page_size=20');
		return response.data.results;
	},
	sendMessage: async (dealId: number, text: string, sellerCompany?: number | null) => {
		const response = await apiClient.post<Message>('crm/messages/', {
			deal: dealId,
			text,
			...(sellerCompany != null ? { seller_company: sellerCompany } : {}),
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
	// On-demand multi-format КП export (PDF / Excel / CSV). Returns an attachment
	// (blob), not JSON; the backend gates seller cost/margin columns server-side.
	exportQuote: async (quoteId: number, format: 'pdf' | 'xlsx' | 'csv') => {
		const response = await apiClient.get(`crm/quotes/${quoteId}/export/`, {
			params: { format },
			responseType: 'blob',
		});
		const blob = new Blob([response.data]);
		const objectUrl = window.URL.createObjectURL(blob);
		const link = document.createElement('a');
		link.href = objectUrl;
		const extension = format === 'xlsx' ? 'xlsx' : format;
		link.setAttribute('download', `RailTech_Quote_${quoteId}.${extension}`);
		document.body.appendChild(link);
		link.click();
		link.remove();
		window.URL.revokeObjectURL(objectUrl);
	},
	// Polls through the 202 GENERATING window (ARCH-03) before saving the blob.
	exportDealPDF: async (dealId: number) => {
		const { downloadFile } = await import('@/lib/download');
		await downloadFile(`crm/deals/${dealId}/export-pdf/`, `RailTech_Quote_${dealId}.pdf`);
	},
	getActivityLogs: async () => {
		const response = await apiClient.get<PaginatedResponse<ActivityLog>>('crm/activity-logs/');
		return response.data.results;
	},
	// CRM Phase A — read-only timeline scoped to a deal or a counterparty company.
	getTimeline: async (params: { deal_id?: number; company_id?: number; limit?: number }) => {
		const response = await apiClient.get<TimelineEntry[]>('crm/timeline/', { params });
		return response.data;
	},
	// ─── CRM Phase B — counterparty book («Книга контрагентов») ─────────────
	// direction=CLIENT → книга клиентов (seller context), SUPPLIER → книга поставщиков (buyer).
	getRelationships: async (direction?: RelationshipDirection) => {
		const response = await apiClient.get<PaginatedResponse<Relationship>>('crm/relationships/', {
			params: direction ? { direction } : undefined,
		});
		return response.data.results;
	},
	// Only the two human-managed fields are writable: stage verdict + account owner.
	updateRelationship: async (id: number, data: { stage?: RelationshipStage; owner_member?: number | null }) => {
		const response = await apiClient.patch<Relationship>(`crm/relationships/${id}/`, data);
		return response.data;
	},
	// Contacts of the team's OWN client book (confidentiality boundary is server-side).
	getContacts: async () => {
		const response = await apiClient.get<PaginatedResponse<Contact>>('accounts/contacts/');
		return response.data.results;
	},
	// «Завести оффлайн-клиента»: company + primary contact in one step → 201 Contact.
	// Errors arrive as {"detail": CODE} — CLIENT_FIELDS_REQUIRED /
	// CONTACT_NEEDS_EMAIL_OR_PHONE / ONLY_SELLER_CAN_CREATE_CLIENTS (apiErrors.* map).
	createOfflineClient: async (payload: OfflineClientPayload) => {
		const response = await apiClient.post<Contact>('accounts/contacts/', payload);
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
	// Seller sets КП-level settings from the builder gear panel: VAT rate, tax country,
	// validity, currency. Seller-guarded PATCH on the same Quote endpoint (backend gates
	// it via can_edit_quote_pricing). vat_rate / valid_until are strings (Decimal/date);
	// tax_country is the Country pk; quote_currency is the Currency code (e.g. "UZS").
	updateQuoteSettings: async (
		id: number,
		data: Partial<Pick<
			Quote,
			| 'vat_rate'
			| 'margin_percent'
			| 'tax_country'
			| 'valid_until'
			| 'quote_currency'
			| 'cost_currency_default'
			| 'fx_manual'
			| 'delivery_lead_time_days'
			| 'delivery_note'
		>>,
	) => {
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
	createQuoteCharge: async (data: { quote: number; charge_type: string; description?: string; amount?: string; rate_percent?: string | null; cost_amount?: string | null; is_deduction?: boolean }) => {
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
	// Reorder the cascade: `order` is the full list of charge ids top→bottom.
	reorderQuoteCharges: async (quoteId: number, order: number[]) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${quoteId}/charges-reorder/`, { order });
		return response.data;
	},
	// ARCH-03: the render is enqueued off-thread — the backend answers 202 GENERATING;
	// poll downloadQuotePDF (it retries on 202) to obtain the fresh file.
	generateQuotePDF: async (id: number) => {
		const response = await apiClient.post<{ detail: string; retry_after: number }>(
			`crm/quotes/${id}/generate-pdf/`,
		);
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
	// Unified approval chain: act on a step (approve/reject) or recall the КП back to draft.
	approvalAct: async (id: number, stepId: number, decision: 'APPROVE' | 'REJECT', comment = '') => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/approval-act/`, {
			step_id: stepId,
			decision,
			comment,
		});
		return response.data;
	},
	recallQuote: async (id: number) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/recall/`);
		return response.data;
	},
	getMyApprovalQueue: async () => {
		const response = await apiClient.get<PaginatedResponse<Quote>>('crm/quotes/my-approval-queue/');
		return response.data.results;
	},
	// Polls through the 202 GENERATING window (lib/download.ts) before saving the blob.
	downloadQuotePDF: async (id: number) => {
		const { downloadFile } = await import('@/lib/download');
		await downloadFile(`crm/quotes/${id}/download-pdf/`, `RailTech_Quote_${id}.pdf`);
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
	// ARCH-01: 202 + task_id, resolved via the ai-status poll (same return shape).
	matchCatalog: async (payload: MatchCatalogPayload) => {
		return runAiJob<{ matches: CatalogMatch[] }>(async () => {
			const response = await apiClient.post<{ task_id: string }>(
				'sourcing/match-catalog/',
				payload,
			);
			return response.data;
		});
	},

	// ─── Pricing-assist (Move 3) ─────────────────────────────
	// GET suggested line costs from the seller's own SupplierOffers for the КП's matched lines.
	// Cost-confidential (only the owning seller); empty {suggestions:[]} when no offers match.
	pricingAssist: async (quoteId: number) => {
		const response = await apiClient.get<{ suggestions: PricingSuggestion[] }>(
			`crm/quotes/${quoteId}/pricing-assist/`,
		);
		return response.data;
	},

	// ─── AI draft-КП generation (Move 3) ─────────────────────
	// Build a pre-filled draft КП from the buyer request (copied lines + pricing-assist on matches).
	// ARCH-01: 202 + task_id, resolved via the ai-status poll. Service gate errors arrive in
	// the result as {error: CODE} and are re-thrown as Error(CODE) for the apiErrors.* map.
	generateDraftQuote: async (dealId: number) => {
		return runAiJob<{ prefilled: number; quote_id: number }>(async () => {
			const response = await apiClient.post<{ task_id: string }>(
				`crm/deals/${dealId}/generate-draft-quote/`,
				{},
			);
			return response.data;
		});
	},

	// ─── AI #7 pre-flight quality check ──────────────────────
	// POST draft request lines → advisory quality findings per line.
	// Advisory only (never blocks submit); may 503 {error:'AI_DISABLED'}.
	// ARCH-01: 202 + task_id, resolved via the ai-status poll (same return shape).
	preflightCheck: async (payload: PreflightPayload) => {
		return runAiJob<{ findings: PreflightFinding[] }>(async () => {
			const response = await apiClient.post<{ task_id: string }>(
				'sourcing/preflight-check/',
				payload,
			);
			return response.data;
		});
	},

	// ─── AI #6 contract/invoice extraction + reconciliation ──
	// POST a signed contract/counter-invoice PDF + a quote OR contract id → extracted
	// fields and a CODE-computed (Decimal) comparison vs the КП/Contract record. The
	// money verdict comes from the backend; LLM numbers are never trusted. May 503.
	// ARCH-01: the multipart POST is unchanged, but the view now returns 202 + task_id;
	// the vision extraction runs on Celery and the result comes from the ai-status poll.
	checkDocument: async ({ file, quoteId, contractId }: DocCheckPayload) => {
		const formData = new FormData();
		formData.append('file', file);
		if (quoteId != null) formData.append('quote_id', String(quoteId));
		if (contractId != null) formData.append('contract_id', String(contractId));
		return runAiJob<DocCheckResult>(async () => {
			const response = await apiClient.post<{ task_id: string }>(
				'sourcing/extract-document/',
				formData,
				{ headers: { 'Content-Type': 'multipart/form-data' } },
			);
			return response.data;
		});
	},

	// ─── AI #4 deal-chat reply assist ────────────────────────
	// POST a deal id → a professional reply DRAFT built from the recent chat history.
	// The draft fills the input for the user to review/edit before sending (never
	// auto-sent). Empty draft when no conversation / no access; may 503 AI_DISABLED.
	// ARCH-01: 202 + task_id, resolved via the ai-status poll (same return shape).
	suggestChatReply: async (dealId: number) => {
		return runAiJob<{ draft: string }>(async () => {
			const response = await apiClient.post<{ task_id: string }>(
				`crm/deals/${dealId}/suggest-reply/`,
				{},
			);
			return response.data;
		});
	},

	// ─── AI #3 «КП vs заявка» coverage / diff ────────────────
	// GET a received КП id → deterministic coverage facts (uncovered lines) plus,
	// when AI is on, semantic discrepancies (non-equivalent substitution, ignored
	// note). Read-only & assistive — never blocks. Scoped to the deal's buyer or
	// the routed seller (403 otherwise).
	// ARCH-01: the GET now returns 202 + task_id; the diff runs on Celery and the
	// result (same shape) is fetched via the ai-status poll.
	quoteRequestDiff: async (quoteId: number) => {
		return runAiJob<QuoteDiffResult>(async () => {
			const response = await apiClient.get<{ task_id: string }>(
				`crm/quotes/${quoteId}/request-diff/`,
			);
			return response.data;
		});
	},
};

