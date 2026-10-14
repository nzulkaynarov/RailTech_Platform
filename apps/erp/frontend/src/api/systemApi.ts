import { apiClient } from './client';

export interface SystemSettings {
	vat_rate: string;
	// standard_margin removed from the settings API surface (P9) — it was inert
	// (the pricing engine reads CompanySettings.default_margin_percent).
	exchange_rate_usd_uzs: string;
	platform_name: string;
	support_email?: string;
	logo_url?: string;
	domain?: string;
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
