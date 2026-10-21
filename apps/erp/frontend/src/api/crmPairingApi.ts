import { apiClient } from './client';

/** Состояние сопряжения с CRM (`GET /api/v1/integration/crm-pairing/`, M3-ERP-05) — без значений ключей. */
export interface CrmPairingStatus {
	/** paired — сопряжено по коду; env — ключи из окружения (запасной путь); none — ключей нет. */
	state: 'paired' | 'env' | 'none';
	paired_at: string | null;
	rotated_at: string | null;
	token_source: 'db' | 'env' | 'none';
	crm_to_erp_last4: string;
	/** Пока идёт переход после «Обновить ключи» в CRM: до какого срока действует прежний токен CRM→ERP. */
	previous_token_valid_until: string | null;
	erp_to_crm_configured: boolean;
	webhook_secret_source: 'db' | 'env' | 'none';
	webhook_secret_last4: string;
	code_ttl_seconds: number;
	crm_frontend_url: string;
}

/** Одноразовый код сопряжения: виден один раз, в ответе на выпуск. */
export interface CrmPairingCode {
	code: string;
	expires_at: string;
	ttl_seconds: number;
}

export const crmPairingApi = {
	getStatus: async (): Promise<CrmPairingStatus> => {
		const response = await apiClient.get<CrmPairingStatus>('integration/crm-pairing/');
		return response.data;
	},

	issueCode: async (): Promise<CrmPairingCode> => {
		const response = await apiClient.post<CrmPairingCode>('integration/crm-pairing/code/');
		return response.data;
	},
};
