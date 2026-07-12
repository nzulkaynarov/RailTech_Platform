import { apiClient } from './client';
import { PaginatedResponse } from './types';

// One live refresh token = one session. The backend stores no ip/user-agent —
// only timestamps and whether the row matches THIS browser's HttpOnly cookie.
export interface Session {
	id: number;
	created_at: string;
	expires_at: string;
	is_current: boolean;
}

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
	is_verified?: boolean;
	has_iso9001?: boolean;
	trust_score?: number;
	bank_account?: string;
	mfo?: string;
	legal_address?: string;
	contact_person?: string;
	contact_info?: string;
	phone?: string;
	country?: number | string | null;
	website?: string;
	email?: string;
	logo?: string | null;
	kyc_notes?: string;
	created_at?: string;
	kyc_documents?: KYCDocument[];
	company_types?: string[];
	user_count?: number;
}

// Per-company document/branding profile printed on КП / contract PDFs.
// OneToOne → Company (accounts.CompanyDocumentProfile). Editable by the
// company OWNER (or platform admin) in the company settings zone.
export interface CompanyDocumentProfile {
	id: number;
	company: number;
	logo_url?: string | null;
	legal_name?: string;
	inn?: string;
	legal_address?: string;
	bank_details?: string;
	signatory_name?: string;
	signatory_position?: string;
	footer_text?: string;
	accent_color?: string;
	use_company_defaults?: boolean;
	// P3 layout toggles — what the seller shows on its documents.
	show_logo?: boolean;
	show_lead_time?: boolean;
	show_fx_note?: boolean;
	created_at?: string;
	updated_at?: string;
}

// OneToOne → Company (accounts.CompanySettings). The selling company's КП
// defaults + document-numbering prefix. Read/written by the company OWNER.
// FK defaults are exposed as master-data CODES (default_*_code, read-only) and
// PATCHed as CODES under default_cost_currency / default_delivery_basis.
export interface CompanySettings {
	id: number;
	company: number;
	default_cost_currency_code?: string | null;
	default_delivery_basis_code?: string | null;
	default_vat_rate?: string | null;
	default_margin_percent?: string | null;
	min_margin_percent?: string | null;     // loss-prevention floor (below → warn + approval)
	target_margin_percent?: string | null;  // healthy target (≥ → green traffic-light)
	default_offer_validity_days?: number | null;
	doc_number_prefix?: string;
	created_at?: string;
	updated_at?: string;
}

// PATCH body for company settings. FK defaults are sent as CODES ("" clears);
// numeric defaults accept null to clear.
export interface CompanySettingsUpdate {
	default_cost_currency?: string;
	default_delivery_basis?: string;
	default_vat_rate?: string | null;
	default_margin_percent?: string | null;
	min_margin_percent?: string | null;
	target_margin_percent?: string | null;
	default_offer_validity_days?: number | null;
	doc_number_prefix?: string;
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
	position?: string;
	role?: number | string | null;
	role_code?: string;
	role_data?: { code: string; name: string };
	workspace_role?: string | null;
	is_platform_admin?: boolean;
	preferences?: { language?: string; theme?: string };
	// Platform-operator sub-role (ADR-0004 G1). Only meaningful when
	// is_platform_admin is true. operator_role is the FK id; operator_role_data
	// is the denormalized {id, code, name} for display.
	operator_role?: number | null;
	operator_role_data?: { id: number; code: string; name: string } | null;
	memberships?: UserMembership[];
	kyc_status?: string | null;
	// Per-membership capabilities from the primary company.
	// OWNER distributes these inside the team; frontend filters
	// the context switcher so a member with can_sell=false does not see
	// SELLER/MANUFACTURER contexts.
	can_sell?: boolean;
	can_buy?: boolean;
	// true/false for sellers, null for non-sellers. false → seller has no
	// operational subscription and seller writes return SUBSCRIPTION_REQUIRED.
	seller_subscription_operational?: boolean | null;
	company?: Company;
	primary_company?: Company;
	is_active?: boolean;
	last_login?: string | null;
	date_joined?: string;
	avatar?: string | null;
	is_2fa_enabled?: boolean;
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
	// Backend filterset key for company type (e.g. 'SUPPLIER'); compared by CODE.
	'types__code'?: string;
	ordering?: string;
	page?: number;
	limit?: number;
	// Follow DRF `next` links and return every matching company, not just page 1
	// (the supplier picker must list ALL sellers, not the first 20).
	fetchAll?: boolean;
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
		if (params?.fetchAll) {
			const query = { ...params };
			delete query.fetchAll;
			const all: Company[] = [];
			let url: string | null = 'accounts/companies/';
			let isFirst = true;
			let guard = 0;
			while (url && guard < 500) {
				const response: { data: PaginatedResponse<Company> } = await apiClient.get<PaginatedResponse<Company>>(
					url,
					isFirst ? { params: query } : undefined,
				);
				all.push(...response.data.results);
				const next = response.data.next;
				url = next ? next.replace(/^.*\/api\/v1\//, '') : null;
				isFirst = false;
				guard += 1;
			}
			return all;
		}
		const response = await apiClient.get<PaginatedResponse<Company>>('accounts/companies/', { params });
		return response.data.results;
	},
	getCompanyDetail: async (id: number) => {
		const response = await apiClient.get<Company>(`accounts/companies/${id}/`);
		return response.data;
	},
	// Buyer-facing verified-supplier directory for the open-RFQ invite flow.
	// Member-accessible (unlike the admin-only full company list); minimal fields.
	getPartnerSuppliers: async (): Promise<{ id: number; name: string; inn: string }[]> => {
		const response = await apiClient.get<{ id: number; name: string; inn: string }[]>('accounts/companies/suppliers/');
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
	// CRM Phase D — invite an offline client's contact to register and claim its company.
	inviteContact: async (contactId: number) => {
		const response = await apiClient.post<{ invited: boolean }>(`accounts/contacts/${contactId}/invite/`);
		return response.data;
	},
	// CRM Phase C — offline placeholder companies matching this company's INN, and the merge.
	getMergeCandidates: async (id: number) => {
		const response = await apiClient.get<{ id: number; name: string; stated_inn: string; is_registered: boolean }[]>(
			`accounts/companies/${id}/merge-candidates/`,
		);
		return response.data;
	},
	mergeCompany: async (survivorId: number, duplicateId: number, reason?: string) => {
		const response = await apiClient.post<{ merged: boolean }>(
			`accounts/companies/${survivorId}/merge/`,
			{ duplicate_id: duplicateId, reason },
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
	// ── Company document profile (КП / contract branding) ──
	getCompanyDocumentProfile: async (companyId: number) => {
		const response = await apiClient.get<CompanyDocumentProfile>(
			`accounts/companies/${companyId}/document-profile/`,
		);
		return response.data;
	},
	updateCompanyDocumentProfile: async (
		companyId: number,
		data: Partial<CompanyDocumentProfile>,
	) => {
		const response = await apiClient.patch<CompanyDocumentProfile>(
			`accounts/companies/${companyId}/document-profile/`,
			data,
		);
		return response.data;
	},
	// Live preview: a SAMPLE КП rendered as HTML with the company's CURRENT profile (branding +
	// toggles). Shown in an iframe on the document-settings panel; refetched after each save.
	getCompanyDocumentProfilePreview: async (companyId: number): Promise<string> => {
		const response = await apiClient.get(
			`accounts/companies/${companyId}/document-profile/preview/`,
			{ responseType: 'text' },
		);
		return response.data as string;
	},
	uploadCompanyDocumentLogo: async (companyId: number, file: File) => {
		const formData = new FormData();
		formData.append('logo', file);
		const response = await apiClient.post<CompanyDocumentProfile>(
			`accounts/companies/${companyId}/document-profile/upload-logo/`,
			formData,
			{ headers: { 'Content-Type': 'multipart/form-data' } },
		);
		return response.data;
	},
	// ── Company settings (КП defaults + document numbering) ──
	getCompanySettings: async (companyId: number) => {
		const response = await apiClient.get<CompanySettings>(
			`accounts/companies/${companyId}/settings/`,
		);
		return response.data;
	},
	updateCompanySettings: async (
		companyId: number,
		data: CompanySettingsUpdate,
	) => {
		const response = await apiClient.patch<CompanySettings>(
			`accounts/companies/${companyId}/settings/`,
			data,
		);
		return response.data;
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
	registerInterest: async (data: { email: string; first_name: string; last_name: string; phone: string }) => {
		const response = await apiClient.post<{ message: string; email: string }>('auth/register/', data);
		return response.data;
	},
	setupPassword: async (data: { uid: string; token: string; password: string }) => {
		const response = await apiClient.post<{ message: string; user: User }>('auth/setup-password/', data);
		return response.data.user;
	},
	forgotPassword: async (email: string) => {
		const response = await apiClient.post<{ message: string }>('auth/forgot-password/', { email });
		return response.data;
	},
	resetPassword: async (data: { uid: string; token: string; password: string }) => {
		const response = await apiClient.post<{ message: string; email: string }>('auth/reset-password/', data);
		return response.data;
	},
	submitProfile: async (data: { companyName: string; position: string; invite?: string }) => {
		const response = await apiClient.post<{ message: string; user: User }>('auth/submit-profile/', {
			companyName: data.companyName,
			position: data.position,
			// CRM Phase D — a CB-invite token claims an existing offline company instead of a new one.
			...(data.invite ? { invite: data.invite } : {}),
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

	// ─── Security & 2FA ───────────────────────────────────────────────
	// Сессии живут под auth/ — HttpOnly refresh-кука ограничена path'ом
	// /api/v1/auth/, и только там бэкенд видит текущий jti (is_current /
	// «завершить остальные» щадит текущую сессию).
	getActiveSessions: async () => {
		const response = await apiClient.get<{ sessions: Session[] }>('auth/sessions/');
		return response.data.sessions;
	},
	revokeAllSessions: async () => {
		const response = await apiClient.post<{ revoked: number }>('auth/sessions/revoke-all/');
		return response.data;
	},
	setup2FA: async () => {
		const response = await apiClient.post<{ secret: string; uri: string }>('auth/2fa/setup/');
		return response.data;
	},
	verify2FA: async (data: { secret: string; code: string; current_password: string }) => {
		const response = await apiClient.post<{ detail: string }>('auth/2fa/verify/', data);
		return response.data;
	},
	disable2FA: async (data: { code: string; current_password: string }) => {
		const response = await apiClient.post<{ detail: string }>('auth/2fa/disable/', data);
		return response.data;
	},

	// ─── Subscriptions (admin) ─────────────────────────────────────────
	getSubscriptions: async (params?: { search?: string; status?: string; plan?: string; ordering?: string }) => {
		const response = await apiClient.get<PaginatedResponse<Subscription>>(
			'accounts/subscriptions/',
			{ params },
		);
		return response.data.results;
	},
	getMySubscription: async (): Promise<Subscription | null> => {
		const response = await apiClient.get<Subscription>('accounts/subscriptions/mine/', {
			validateStatus: (s) => s === 200 || s === 204 || s === 403,
		});
		if (response.status === 200) return response.data;
		return null;
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
	updateMemberCapabilities: async (
		companyId: number,
		payload: { member_id: number; can_sell?: boolean; can_buy?: boolean },
	) => {
		const response = await apiClient.post<{
			id: number; user_id: number; can_sell: boolean; can_buy: boolean;
		}>(`accounts/companies/${companyId}/update-member-capabilities/`, payload);
		return response.data;
	},
	// Company Admin changes a member's workspace role (promote/demote/transfer).
	setMemberRole: async (companyId: number, payload: { member_id: number; role: string }) => {
		const response = await apiClient.post<{ id: number; user_id: number; role: string }>(
			`accounts/companies/${companyId}/set-member-role/`,
			payload,
		);
		return response.data;
	},
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

	// ─── Company Roles (custom RBAC) ──────────────────────────────────
	getCompanyRoles: async (companyId?: number) => {
		const url = companyId
			? `accounts/company-roles/?company=${companyId}`
			: 'accounts/company-roles/';
		// DRF list is paginated — unwrap to the array the UI maps over.
		const response = await apiClient.get<PaginatedResponse<CompanyRole>>(url);
		return response.data.results;
	},
	createCompanyRole: async (data: { name: string; permissions: string[] }) => {
		const response = await apiClient.post<CompanyRole>('accounts/company-roles/', data);
		return response.data;
	},
	updateCompanyRole: async (id: number, data: { name?: string; permissions?: string[] }) => {
		const response = await apiClient.patch<CompanyRole>(`accounts/company-roles/${id}/`, data);
		return response.data;
	},
	deleteCompanyRole: async (id: number) => {
		await apiClient.delete(`accounts/company-roles/${id}/`);
	},
	assignMemberRole: async (payload: { member_id: number; role_id: number }) => {
		const response = await apiClient.post<{ id: number; company_role: number | null }>(
			'accounts/company-roles/assign/',
			payload,
		);
		return response.data;
	},
	getPermissionCatalog: async () => {
		// Backend returns { groups: [...] } — unwrap to the array the UI maps over.
		const response = await apiClient.get<{ groups: PermissionGroup[] }>('accounts/permissions/');
		return response.data.groups;
	},

	// ─── Role Applications (admin + owner self-service) ────────────────
	getRoleApplications: async (params?: { search?: string; status?: string; requested_type?: string; ordering?: string }) => {
		const response = await apiClient.get<PaginatedResponse<RoleApplication>>(
			'accounts/role-applications/',
			{ params },
		);
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

export interface CompanyRole {
	id: number;
	name: string;
	permissions: string[];
	is_system: boolean;
	member_count: number;
}

export interface PermissionDef {
	code: string;
	label: string;
}

export interface PermissionGroup {
	key: string;
	label: string;
	permissions: PermissionDef[];
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
