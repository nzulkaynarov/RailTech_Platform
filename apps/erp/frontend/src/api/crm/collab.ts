/**
 * Совместная работа вокруг сделки: статус фоновых задач, выгрузки, лента активности,
 * таймлайн, контакты книги клиентов и офлайн-клиенты (книга контрагентов удалена в M1-ERP-02 волна 3).
 *
 * Вынесено из crmApi.ts при распиле (1179 строк, 56 правок — самый горячий файл проекта).
 * Composed в `./index.ts`; публичный объект `crmApi` и путь `@/api/crmApi` не изменились.
 */

import { apiClient } from '../client';
import { PaginatedResponse } from '../types';
import type { Contact, OfflineClientPayload, TimelineEntry } from './types';

export const collabApi = {
	getTaskStatus: async (taskId: string) => {
		const response = await apiClient.get<{
			task_id: string;
			status: string;
			result: unknown;
			meta?: { current: number; total: number };
		}>(`sourcing/import-status/${taskId}/`);
		return response.data;
	},
	// Polls through the 202 GENERATING window (ARCH-03) before saving the blob.
	exportDealPDF: async (dealId: number) => {
		const { downloadFile } = await import('@/lib/download');
		await downloadFile(`crm/deals/${dealId}/export-pdf/`, `Quote_${dealId}.pdf`);
	},	// CRM Phase A — read-only timeline scoped to a deal or a counterparty company.
	getTimeline: async (params: { deal_id?: number; company_id?: number; limit?: number }) => {
		const response = await apiClient.get<TimelineEntry[]>('crm/timeline/', { params });
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
};
