import { apiClient } from './client';

export interface SystemSettings {
	vat_rate: string;
	// standard_margin removed from the settings API surface (P9) — it was inert
	// (the pricing engine reads CompanySettings.default_margin_percent).
	/** Курс USD→UZS из справочника ЦБ (`finance.services.fx`), только чтение; null — свежего курса нет (FIX-41). */
	readonly exchange_rate_usd_uzs: string | null;
	/** Общие для ансамбля поля — ведутся в CRM, в ERP только просмотр; PATCH с ними — 400 SHARED_SETTING_READ_ONLY (FIX-42). */
	readonly platform_name: string;
	readonly support_email?: string;
	readonly logo_url?: string;
	readonly domain?: string;
	/** Адрес CRM для ссылки «Изменить в CRM» (CRM_FRONTEND_URL), только чтение. */
	readonly crm_frontend_url?: string;
	maintenance_mode: boolean;
	is_two_factor_required: boolean;
	updated_at: string;
}

export const systemApi = {
	getSettings: async (): Promise<SystemSettings> => {
		const response = await apiClient.get<SystemSettings>('system-settings/');
		return response.data;
	},

	updateSettings: async (data: Partial<SystemSettings>): Promise<SystemSettings> => {
		const response = await apiClient.patch<SystemSettings>('system-settings/', data);
		return response.data;
	},
};
