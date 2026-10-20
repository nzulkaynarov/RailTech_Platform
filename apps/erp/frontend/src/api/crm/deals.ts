/**
 * Сделки и заявки: CRUD, взятие в работу, этапы воронки, шаблоны статей расхода.
 * Маршрутизация продавцам (R1/R3) и покупательские действия с заявкой (строки, отправка)
 * удалены в M1-ERP-02 волна 3: продавец один, заявку клиент подаёт в Cabinet.
 *
 * Вынесено из crmApi.ts при распиле (1179 строк, 56 правок — самый горячий файл проекта).
 * Composed в `./index.ts`; публичный объект `crmApi` и путь `@/api/crmApi` не изменились.
 */

import { apiClient } from '../client';
import { fetchAllPages } from '../fetchAllPages';
import { PaginatedResponse } from '../types';
import type { ChargeTemplate, Deal, DealDocumentHub, QuoteItem, QuoteItemDisplayType, TimeToFirstQuoteStats } from './types';

export const dealsApi = {
	// `fetchAll` — для экранов, которые показывают СПИСОК СДЕЛОК ЦЕЛИКОМ и пейджера не имеют:
	// реестр «Сделки», выбор сделки в мастере документов. Без него 21-я сделка была
	// недостижима — ни открыть, ни выставить по ней счёт. Виджеты дашборда и чек-лист онбординга берут первую страницу СОЗНАТЕЛЬНО: они
	// показывают верхние N по свежести, а не весь список.
	getDeals: async (opts?: { fetchAll?: boolean }) => {
		if (opts?.fetchAll) return fetchAllPages<Deal>('crm/deals/');
		const response = await apiClient.get<PaginatedResponse<Deal>>('crm/deals/');
		return response.data.results;
	},
	getDeal: async (id: number) => {
		const response = await apiClient.get<Deal>(`crm/deals/${id}/`);
		return response.data;
	},
	// `contact_id` opens the deal FOR an offline client from the company's own book
	// (Wave E F2); `without_client` opens a company-less «калькулятор» draft (F3).
	createDeal: async (data: { title?: string; notes?: string; contact_id?: number; without_client?: boolean }) => {
		const response = await apiClient.post<Deal>('crm/deals/', data);
		return response.data;
	},
	createQuoteItem: async (data: { quote: number; imported_raw_name: string; quantity?: number; frozen_base_price?: string; frozen_currency?: string; lead_time_days?: number; display_type?: QuoteItemDisplayType; is_optional?: boolean }) => {
		const response = await apiClient.post<QuoteItem>('crm/quote-items/', data);
		return response.data;
	},
	deleteQuoteItem: async (id: number) => {
		await apiClient.delete(`crm/quote-items/${id}/`);
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
	// F1: цепочка документов сделки одним запросом — договор, счета, акты, отгрузка и
	// подсказка следующего шага. Один ключ кэша вместо пяти списочных запросов.
	getDealDocuments: async (dealId: number): Promise<DealDocumentHub> => {
		const response = await apiClient.get<DealDocumentHub>(`crm/deals/${dealId}/documents/`);
		return response.data;
	},
	changeDealStage: async (dealId: number, stageCode: string) => {
		const response = await apiClient.post<Deal>(`crm/deals/${dealId}/change-stage/`, { stage_code: stageCode });
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
	// ─── Quote item re-match ─────────────────────────────────
};
