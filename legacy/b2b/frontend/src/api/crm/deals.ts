/**
 * Сделки и заявки: CRUD, взятие в работу, маршрутизация продавцам (R1/R3), этапы воронки,
 * шаблоны статей расхода и лиды.
 *
 * Вынесено из crmApi.ts при распиле (1179 строк, 56 правок — самый горячий файл проекта).
 * Composed в `./index.ts`; публичный объект `crmApi` и путь `@/api/crmApi` не изменились.
 */

import { runAiJob } from '@/lib/aiJob';
import { apiClient } from '../client';
import { fetchAllPages } from '../fetchAllPages';
import { PaginatedResponse } from '../types';
import type { ChargeTemplate, Deal, DealDocumentHub, Lead, QuoteItem, QuoteItemDisplayType, SellerCompanyRef, SuggestedSeller, TimeToFirstQuoteStats } from './types';

export const dealsApi = {
	/**
	 * Список сделок. `context` задаёт скоуп ЯВНО — им пользуются продавцовые виджеты дашборда:
	 * дашборд общий для обеих ролей, поэтому глобальный `activeStatus` там остаётся BUYER, и
	 * без явного SELLER плитки продавца считались по покупательской выборке (03-08).
	 */
	// `fetchAll` — для экранов, которые показывают СПИСОК СДЕЛОК ЦЕЛИКОМ и пейджера не имеют:
	// реестр сделок оператора, «Мои заявки» покупателя, «Сделки» продавца, выбор сделки в
	// мастере документов. Без него 21-я сделка была недостижима — ни открыть, ни выставить по
	// ней счёт. Виджеты дашборда и чек-лист онбординга берут первую страницу СОЗНАТЕЛЬНО: они
	// показывают верхние N по свежести, а не весь список.
	getDeals: async (context?: 'BUYER' | 'SELLER', opts?: { fetchAll?: boolean }) => {
		const headers = context ? { 'X-Active-Context': context } : undefined;
		if (opts?.fetchAll) return fetchAllPages<Deal>('crm/deals/', undefined, { headers });
		const response = await apiClient.get<PaginatedResponse<Deal>>('crm/deals/', { headers });
		return response.data.results;
	},
	getDeal: async (id: number) => {
		const response = await apiClient.get<Deal>(`crm/deals/${id}/`);
		return response.data;
	},
	// `contact_id` opens the deal FOR an offline client from the seller's own book
	// (Wave E F2); `without_client` opens a company-less «калькулятор» draft (F3).
	// Both are seller-side; omitting them keeps the buyer-initiated behaviour.
	createDeal: async (data: { title?: string; notes?: string; contact_id?: number; without_client?: boolean }) => {
		const response = await apiClient.post<Deal>('crm/deals/', data);
		return response.data;
	},	createQuoteItem: async (data: { quote: number; imported_raw_name: string; quantity?: number; frozen_base_price?: string; frozen_currency?: string; lead_time_days?: number; display_type?: QuoteItemDisplayType; is_optional?: boolean }) => {
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
	// F1: цепочка документов сделки одним запросом — договор, счета, акты, отгрузка + сторона
	// зрителя и подсказка следующего шага. Один ключ кэша вместо пяти списочных запросов.
	getDealDocuments: async (dealId: number): Promise<DealDocumentHub> => {
		const response = await apiClient.get<DealDocumentHub>(`crm/deals/${dealId}/documents/`);
		return response.data;
	},
	// R1 (spec-freetext-rfq-routing): предложенные продавцы по позициям заявки (trigram-матч
	// к каталогу, счёт совпавших позиций). Read-only подсказка для шага выбора получателей.
	getSuggestedSellers: async (dealId: number): Promise<SuggestedSeller[]> => {
		const response = await apiClient.get<SuggestedSeller[]>(`crm/deals/${dealId}/suggested-sellers/`);
		return response.data;
	},
	// R3: AI-enhanced подбор продавцов — free-text позиции без trigram-совпадения добираются
	// одним билингвальным LLM-вызовом. ARCH-01: 202 + task_id → ai-status poll. Может вернуть
	// 503 {error:'AI_DISABLED'} / 429 {error:'AI_DAILY_CAP_REACHED'} (re-thrown как Error(CODE)).
	suggestSellersAi: async (dealId: number): Promise<{ sellers: SuggestedSeller[] }> => {
		return runAiJob<{ sellers: SuggestedSeller[] }>(async () => {
			const response = await apiClient.post<{ task_id: string }>(`crm/deals/${dealId}/suggest-sellers-ai/`);
			return response.data;
		});
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
	// Лиды — очередь обработки: страница печатает «Новых N» по этому же списку и пейджера не
	// имеет. Первая страница вместо всего списка означала, что 21-й лид не обработает никто и
	// счётчик про него не скажет.
	listLeads: async () => fetchAllPages<Lead>('crm/leads/'),
	/** Оператор НАЗНАЧАЕТ лид компании (Salesforce lead assignment) — сделку он не создаёт. */
	routeLead: async (leadId: number, companyId: number, reason: string) => {
		const response = await apiClient.post<Lead>(`crm/leads/${leadId}/route/`, {
			company_id: companyId,
			reason,
		});
		return response.data;
	},
	/** Спам или дубль: лид закрывается площадкой с причиной, сделка не создаётся. */
	rejectLead: async (leadId: number, reason: string) => {
		const response = await apiClient.post<Lead>(`crm/leads/${leadId}/reject/`, { reason });
		return response.data;
	},
	/** Компания берёт назначенный ей лид в работу — и становится владельцем сделки. */
	claimLead: async (leadId: number) => {
		const response = await apiClient.post<{ deal_id: number; stage: string }>(`crm/leads/${leadId}/claim/`);
		return response.data;
	},

	// ─── Quote item re-match ─────────────────────────────────
};
