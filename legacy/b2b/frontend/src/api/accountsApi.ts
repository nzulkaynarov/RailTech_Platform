import { apiClient } from './client';
import { PaginatedResponse } from './types';

export interface KYCDocument {
	id: number;
	doc_type: number;
	doc_type_display: string;
	file?: string | null;
	original_filename: string;
	uploaded_at: string;
}

export interface Company {
	id: number;
	name: string;
	inn: string;
	verification_status: number | string;
	verification_status_code?: string;
	verification_status_name?: string;
	bank_account?: string;
	mfo?: string;
	legal_address?: string;
	contact_person?: string;
	contact_info?: string;
	country?: string;
	website?: string;
	email?: string;
	logo?: string | null;
	kyc_notes?: string;
	created_at?: string;
	kyc_documents?: KYCDocument[];
	company_types?: string[];
	user_count?: number;
}

export interface UserMembership {
	id: number;
	company: number;
	company_name?: string;
	role?: number | null;
	role_code?: string;
	role_name?: string;
	is_primary?: boolean;
	is_active?: boolean;
	can_sell?: boolean;
	can_buy?: boolean;
}

export interface User {
	id: number;
	username: string;
	email: string;
	first_name: string;
	last_name: string;
	phone: string;
	role?: number | string | null;
	role_code?: string;
	role_data?: { code: string; name: string };
	workspace_role?: string | null;
	is_platform_admin?: boolean;
	memberships?: UserMembership[];
	kyc_status?: string | null;
	// Per-membership capabilities from the primary company.
	// OWNER distributes these inside the team; frontend filters
	// the context switcher so a member with can_sell=false does not see
	// SELLER/MANUFACTURER contexts.
	can_sell?: boolean;
	can_buy?: boolean;
	company?: Company;
	primary_company?: Company;
	is_active?: boolean;
	last_login?: string | null;
	date_joined?: string;
	avatar?: string | null;
}

/** Map backend `primary_company` → frontend `company` field */
function normalizeUser(u: User): User {
	if (u.primary_company && !u.company) {
		u.company = u.primary_company;
	}
	return u;
}

export interface CompanyFilterParams {
	search?: string;
	verification_status?: string;
	ordering?: string;
	page?: number;
	limit?: number;
	[key: string]: string | number | boolean | undefined;
}

export interface UserFilterParams {
	search?: string;
	role?: string;
	is_active?: boolean;
	company_id?: number;
	ordering?: string;
	page?: number;
	limit?: number;
	[key: string]: string | number | boolean | undefined;
}

export const accountsApi = {
	getMe: async () => {
		const response = await apiClient.get<User>('accounts/users/me/');
		return response.data;
	},
	getCompanies: async (params?: CompanyFilterParams) => {
		const response = await apiClient.get<PaginatedResponse<Company>>('accounts/companies/', { params });
		return response.data.results;
	},
	getCompanyDetail: async (id: number) => {
		const response = await apiClient.get<Company>(`accounts/companies/${id}/`);
		return response.data;
	},
	createCompany: async (data: Partial<Company>) => {
		const response = await apiClient.post<Company>('accounts/companies/', data);
		return response.data;
	},
	updateCompany: async (id: number, data: Partial<Company>) => {
		const response = await apiClient.patch<Company>(`accounts/companies/${id}/`, data);
		return response.data;
	},
	deleteCompany: async (id: number) => {
		await apiClient.delete(`accounts/companies/${id}/`);
	},
	verifyCompany: async (id: number, statusCode: string, comment?: string, reason?: string) => {
		const response = await apiClient.post(
			`accounts/companies/${id}/verify-kyc/`,
			{ status_code: statusCode, comment, reason },
		);
		return response.data;
	},
	uploadDocument: async (companyId: number, file: File, docType: string) => {
		const formData = new FormData();
		formData.append('file', file);
		formData.append('doc_type', docType);
		const response = await apiClient.post<KYCDocument>(
			`accounts/companies/${companyId}/upload-document/`,
			formData,
			{ headers: { 'Content-Type': 'multipart/form-data' } }
		);
		return response.data;
	},
	deleteDocument: async (companyId: number, docId: number) => {
		await apiClient.delete(`accounts/companies/${companyId}/delete-document/${docId}/`);
	},
	uploadCompanyLogo: async (companyId: number, file: File) => {
		const formData = new FormData();
		formData.append('logo', file);
		const response = await apiClient.post<Company>(
			`accounts/companies/${companyId}/upload-logo/`,
			formData,
			{ headers: { 'Content-Type': 'multipart/form-data' } },
		);
		return response.data;
	},
	deleteCompanyLogo: async (companyId: number) => {
		await apiClient.delete(`accounts/companies/${companyId}/delete-logo/`);
	},
	uploadAvatar: async (file: File) => {
		const formData = new FormData();
		formData.append('avatar', file);
		const response = await apiClient.post<User>(
			'accounts/users/upload-avatar/',
			formData,
			{ headers: { 'Content-Type': 'multipart/form-data' } },
		);
		return response.data;
	},
	deleteAvatar: async () => {
		await apiClient.delete('accounts/users/delete-avatar/');
	},
	uploadUserAvatar: async (userId: number, file: File) => {
		const formData = new FormData();
		formData.append('avatar', file);
		const response = await apiClient.post<User>(
			`accounts/users/${userId}/upload-avatar/`,
			formData,
			{ headers: { 'Content-Type': 'multipart/form-data' } },
		);
		return response.data;
	},
	deleteUserAvatar: async (userId: number) => {
		await apiClient.delete(`accounts/users/${userId}/delete-avatar/`);
	},
	getTeam: async (companyId: number) => {
		const response = await apiClient.get<User[]>(`accounts/companies/${companyId}/team/`);
		return response.data;
	},
	inviteUser: async (companyId: number, data: { email: string; role: string }) => {
		const response = await apiClient.post<User>(`accounts/companies/${companyId}/invite/`, data);
		return response.data;
	},
	registerInterest: async (data: { email: string; first_name: string; last_name: string }) => {
		const response = await apiClient.post<{ message: string; email: string }>('auth/register/', data);
		return response.data;
	},
	setupPassword: async (data: { uid: string; token: string; password: string }) => {
		const response = await apiClient.post<{ message: string; user: User }>('auth/setup-password/', data);
		return response.data.user;
	},
	submitProfile: async (data: { inn: string; companyName: string; role: string; company_type?: string }) => {
		const response = await apiClient.post<{ message: string; user: User }>('auth/submit-profile/', {
			inn: data.inn,
			companyName: data.companyName,
			role_code: data.role,
			company_type: data.company_type || 'CLIENT',
		});
		return response.data.user;
	},
	// Admin specific endpoints
	getUsers: async (params?: UserFilterParams) => {
		const response = await apiClient.get<PaginatedResponse<User>>('accounts/users/', { params });
		return response.data.results.map(normalizeUser);
	},
	toggleUserActiveStatus: async (id: number) => {
		const response = await apiClient.post<{ status: string; is_active: boolean }>(`accounts/users/${id}/toggle-active/`);
		return response.data;
	},
	updateUser: async (id: number, data: Partial<User>) => {
		const response = await apiClient.patch<User>(`accounts/users/${id}/`, data);
		return response.data;
	},
	updateUserRole: async (id: number, role: string) => {
		const response = await apiClient.post<User>(`accounts/users/${id}/change-role/`, { role });
		return response.data;
	},
	createUser: async (data: Partial<User>) => {
		const response = await apiClient.post<User>('accounts/users/', data);
		return response.data;
	},
	deleteUser: async (id: number) => {
		await apiClient.delete(`accounts/users/${id}/`);
	},
	updateMe: async (data: Partial<User>) => {
		const response = await apiClient.patch<User>('accounts/users/update-me/', data);
		return response.data;
	},
	changePassword: async (data: { current_password: string; new_password: string }) => {
		const response = await apiClient.post<{ message: string }>('accounts/users/change-password/', data);
		return response.data;
	},

	// ─── Subscriptions (admin) ─────────────────────────────────────────
	getSubscriptions: async () => {
		const response = await apiClient.get<PaginatedResponse<Subscription>>('accounts/subscriptions/');
		return response.data.results;
	},
	activateSubscription: async (id: number) => {
		const response = await apiClient.post<Subscription>(`accounts/subscriptions/${id}/activate/`);
		return response.data;
	},
	suspendSubscription: async (id: number) => {
		const response = await apiClient.post<Subscription>(`accounts/subscriptions/${id}/suspend/`);
		return response.data;
	},
	paySubscription: async (id: number, amount: string, months = 1) => {
		const response = await apiClient.post<Subscription>(
			`accounts/subscriptions/${id}/pay/`,
			{ amount, months },
		);
		return response.data;
	},
	createSubscription: async (data: Partial<Subscription>) => {
		const response = await apiClient.post<Subscription>('accounts/subscriptions/', data);
		return response.data;
	},
	updateSubscription: async (id: number, data: Partial<Subscription>) => {
		const response = await apiClient.patch<Subscription>(`accounts/subscriptions/${id}/`, data);
		return response.data;
	},
	deleteSubscription: async (id: number) => {
		await apiClient.delete(`accounts/subscriptions/${id}/`);
	},

	// ─── System Roles (admin) ──────────────────────────────────────────
	getSystemRoles: async () => {
		const response = await apiClient.get<{ code: string; name: string }[]>('accounts/system-roles/');
		return response.data;
	},

	// ─── Company Types (authenticated lookup) ──────────────────────────
	getCompanyTypes: async () => {
		const response = await apiClient.get<{ id: number; code: string; name: string }[]>('accounts/company-types/');
		return response.data;
	},

	// ─── Workspace Roles ───────────────────────────────────────────────
	getWorkspaceRoles: async (companyType?: string) => {
		const url = companyType
			? `accounts/workspace-roles/?company_type=${encodeURIComponent(companyType)}`
			: 'accounts/workspace-roles/';
		const response = await apiClient.get<{ code: string; name: string; applicable_to_types: string[] }[]>(url);
		return response.data;
	},

	// ─── User Memberships (admin) ──────────────────────────────────────
	addUserMembership: async (userId: number, data: { company: number; workspace_role: string; is_primary?: boolean }) => {
		const response = await apiClient.post<{
			id: number; company_id: number; company_name: string;
			workspace_role: string; is_primary: boolean;
		}>(`accounts/users/${userId}/add-membership/`, data);
		return response.data;
	},
	removeUserMembership: async (userId: number, membershipId: number) => {
		await apiClient.delete(`accounts/users/${userId}/remove-membership/${membershipId}/`);
	},

	// ─── Role Applications (admin + owner self-service) ────────────────
	getRoleApplications: async () => {
		const response = await apiClient.get<PaginatedResponse<RoleApplication>>('accounts/role-applications/');
		return response.data.results;
	},
	createRoleApplication: async (data: {
		company: number;
		requested_type: number;
		contract_file?: File | null;
		nda_file?: File | null;
		partnership_agreement?: File | null;
	}) => {
		const formData = new FormData();
		formData.append('company', String(data.company));
		formData.append('requested_type', String(data.requested_type));
		if (data.contract_file) formData.append('contract_file', data.contract_file);
		if (data.nda_file) formData.append('nda_file', data.nda_file);
		if (data.partnership_agreement) formData.append('partnership_agreement', data.partnership_agreement);
		const response = await apiClient.post<RoleApplication>(
			'accounts/role-applications/',
			formData,
			{ headers: { 'Content-Type': 'multipart/form-data' } },
		);
		return response.data;
	},
	approveRoleApplication: async (id: number) => {
		const response = await apiClient.post<RoleApplication>(`accounts/role-applications/${id}/approve/`);
		return response.data;
	},
	rejectRoleApplication: async (id: number, reason?: string) => {
		const response = await apiClient.post<RoleApplication>(
			`accounts/role-applications/${id}/reject/`,
			reason ? { reason } : {},
		);
		return response.data;
	},
};

// ─── Types ──────────────────────────────────────────────────────────────

export interface Subscription {
	id: number;
	company: number;
	company_name: string;
	company_inn: string;
	plan: string;
	plan_display: string;
	status: string;
	status_display: string;
	monthly_rate: string;
	currency: number | null;
	currency_code: string | null;
	valid_from: string | null;
	valid_until: string | null;
	last_payment_date: string | null;
	next_payment_date: string | null;
	notes: string;
	created_at: string;
	updated_at: string;
}

export interface RoleApplication {
	id: number;
	company: number;
	company_name: string;
	company_inn: string;
	requested_type: number;
	requested_type_name: string;
	requested_type_code: string;
	status: string;
	status_display: string;
	submitted_by: number | null;
	submitted_by_email: string | null;
	contract_file: string | null;
	nda_file: string | null;
	partnership_agreement: string | null;
	reviewed_by: number | null;
	reviewed_by_email: string | null;
	review_notes: string;
	reviewed_at: string | null;
	created_at: string;
	updated_at: string;
}
