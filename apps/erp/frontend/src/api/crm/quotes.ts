/**
 * Жизненный цикл КП: создание и настройки, статьи расхода, отправка клиенту, цепочка
 * внутреннего согласования, публичная ссылка.
 *
 * Вынесено из crmApi.ts при распиле (1179 строк, 56 правок — самый горячий файл проекта).
 * Composed в `./index.ts`; публичный объект `crmApi` и путь `@/api/crmApi` не изменились.
 */

import { apiClient } from '../client';
import { PaginatedResponse } from '../types';
import type { Quote, QuoteApprovalPreview, QuoteCharge } from './types';

export const quotesApi = {
	getQuotes: async () => {
		const response = await apiClient.get<PaginatedResponse<Quote>>('crm/quotes/');
		return response.data.results;
	},
	getQuote: async (id: number) => {
		const response = await apiClient.get<Quote>(`crm/quotes/${id}/`);
		return response.data;
	},
	// Read-only «who would have to approve this КП if submitted now» (Salesforce Approval
	// Preview) — builds nothing, persists nothing. Surfaced in the DRAFT approval popover.
	getQuoteApprovalPreview: async (id: number) => {
		const response = await apiClient.get<QuoteApprovalPreview>(`crm/quotes/${id}/approval-preview/`);
		return response.data;
	},
	createQuote: async (data: { deal: number; notes?: string; valid_until?: string }) => {
		const response = await apiClient.post<Quote>('crm/quotes/', data);
		return response.data;
	},
	// WP-G1 — «Дублировать КП» (Odoo Duplicate). Deep-copies the source quote into a new DRAFT
	// on the SAME deal (version+1, lines + charges carried over) and returns the new Quote.
	// Endpoint added by the parallel backend lane; the duplicate control degrades to an error
	// toast (translateApiError) if it 404s in a build where the backend has not landed yet.
	duplicateQuote: async (id: number) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/duplicate/`, {});
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
	// Re-pull the seller company's CURRENT defaults (VAT / margin / basis / validity /
	// cost currency) into this DRAFT КП, overwriting those five fields (Odoo «Update
	// Prices»). Returns the field codes that actually changed (for the UI summary).
	applyQuoteDefaults: async (id: number) => {
		const response = await apiClient.post<{ changed_fields: string[] }>(`crm/quotes/${id}/apply-defaults/`);
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
	},	sendQuoteToClient: async (id: number, justification?: string) => {
		// S7a: `justification` is required only when the КП is below the margin floor (the backend
		// gate returns BELOW_FLOOR_JUSTIFICATION_REQUIRED otherwise); it is ignored above the floor.
		const body = justification && justification.trim() ? { justification: justification.trim() } : {};
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/send-to-client/`, body);
		return response.data;
	},
	approveQuote: async (id: number) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/approve/`);
		return response.data;
	},
	// Wave B2 — revoke the КП's public no-login link (PandaDoc «отозвать ссылку»). Sets
	// public_token_revoked so the shared page starts answering 410 GONE. The backend gate
	// mirrors send-to-client (own SENT КП only). Endpoint added by the parallel B1 lane; the
	// post-send panel only renders this action once a share token is actually exposed.
	revokePublicLink: async (id: number) => {
		const response = await apiClient.post<Quote>(`crm/quotes/${id}/revoke-public-link/`);
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
	// ─── Lead ops ─────────────────────────────────────────────
};
