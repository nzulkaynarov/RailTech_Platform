import { apiClient } from './client';
import type { components } from './schema';

/**
 * M1-ERP-08 — отклонение маржи сделки и факт закупки (вручную до M4).
 * Типы — только сгенерированные из OpenAPI (`schema.d.ts`).
 */
export type MarginDeviation = components['schemas']['MarginDeviation'];
export type MarginDeviationRow = components['schemas']['MarginDeviationRow'];
export type PurchaseActualPayload = components['schemas']['PurchaseActualRequest'];

export const financeApi = {
	getMarginDeviation: async (dealId: number) => {
		const response = await apiClient.get<MarginDeviation>(`finance/deals/${dealId}/margin-deviation/`);
		return response.data;
	},
	recordPurchaseActual: async (dealId: number, data: PurchaseActualPayload) => {
		const response = await apiClient.post<MarginDeviation>(`finance/deals/${dealId}/purchase-actuals/`, data);
		return response.data;
	},
	removePurchaseActual: async (dealId: number, currency: string) => {
		const response = await apiClient.delete<MarginDeviation>(
			`finance/deals/${dealId}/purchase-actuals/${encodeURIComponent(currency)}/`,
		);
		return response.data;
	},
};
