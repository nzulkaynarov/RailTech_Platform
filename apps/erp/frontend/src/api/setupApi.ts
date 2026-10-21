import { apiClient } from './client';

/** Мастер первого запуска (FIX-65): нужна ли ERP первоначальная настройка и может ли её сделать текущий пользователь. */
export interface SetupStatus {
	setup_required: boolean;
	can_setup: boolean;
}

export interface OwnCompanyInput {
	name: string;
	inn?: string;
	legal_address?: string;
	phone?: string;
	email?: string;
}

export const setupApi = {
	getStatus: async (): Promise<SetupStatus> => {
		const response = await apiClient.get<SetupStatus>('setup/status/');
		return response.data;
	},

	createOwnCompany: async (data: OwnCompanyInput): Promise<{ id: number; name: string }> => {
		const response = await apiClient.post<{ id: number; name: string }>('setup/company/', data);
		return response.data;
	},
};
