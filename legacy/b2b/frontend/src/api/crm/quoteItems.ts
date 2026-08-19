/**
 * Позиции КП: чтение с фильтрами, точечные и пакетные правки, подбор товаров, импорт из Excel.
 *
 * Вынесено из crmApi.ts при распиле (1179 строк, 56 правок — самый горячий файл проекта).
 * Composed в `./index.ts`; публичный объект `crmApi` и путь `@/api/crmApi` не изменились.
 */

import { apiClient } from '../client';
import { PaginatedResponse } from '../types';
import type { Product, QuoteItem } from './types';

export const quoteItemsApi = {
	getQuoteItems: async (params?: { quote?: number, deal_id?: number, product_is_null?: boolean }) => {
		let url = 'crm/quote-items/';
		if (params) {
			const query = new URLSearchParams();
			// Backend filterset key is `quote__deal_id` (QuoteItemViewSet.filterset_fields).
			// Sending `deal_id` was silently IGNORED by DRF → the КП builder loaded the
			// seller's items from ALL deals (opening one deal's КП showed another's lines).
			// `quote` — позиции ОДНОГО документа. У сделки бывает несколько КП (контейнер
			// строк заявки покупателя + КП продавца), и фильтр по сделке смешивает их:
			// билдер показывал 4 позиции вместо 2, половину — с нулевой ценой.
			if (params.quote) query.append('quote', params.quote.toString());
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
	// Транзакционное массовое удаление строк КП: ОДИН запрос, ОДНА блокировка КП, ОДИН пересчёт.
	// Раньше здесь уходили N ПАРАЛЛЕЛЬНЫХ DELETE — они брали блокировки вразнобой и стабильно
	// ловили deadlock в Postgres: часть строк исчезала, часть оставалась, а пользователь видел
	// только «Operation failed» (найдено прогоном глазами 19-08).
	bulkDeleteQuoteItems: async (quoteId: number, ids: number[]) => {
		const response = await apiClient.post<{ deleted: number[] }>('crm/quote-items/bulk-delete/', {
			quote: quoteId,
			items: ids,
		});
		return response.data.deleted;
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
};
