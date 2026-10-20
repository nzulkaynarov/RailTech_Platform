import { apiClient } from './client';
import { fetchAllPages } from './fetchAllPages';
import { PaginatedResponse } from './types';

// One live refresh token = one session. The backend stores no ip/user-agent —
// only timestamps and whether the row matches THIS browser's HttpOnly cookie.
export interface Session {
	id: number;
	created_at: string;
	expires_at: string;
	is_current: boolean;
}

export interface Company {
	id: number;
	name: string;
	inn: string;
	/** Компания в обороте. `false` — архивирована: скрыта из подбора, история сохранена. */
	is_active?: boolean;
	archived_at?: string | null;
	archived_reason?: string;
	/** Способность объявлена ЗАРАНЕЕ (Salesforce `deletable`) — кнопка не должна гарантированно падать. */
	can_delete?: boolean;
	delete_blocker?: string | null;
	has_iso9001?: boolean;
	trust_score?: number;
	bank_account?: string;
	mfo?: string;
	legal_address?: string;
	contact_person?: string;
	// `contact_info` здесь НЕ БЫЛО НИКОГДА — у модели поле называется `phone`. Пока фантомное
	// поле стояло в типе, форма реестра компаний компилировалась и слала его в PATCH: DRF молча
	// выбрасывал незнакомый ключ, ответ приходил 200, и оператор видел зелёный тост при нулевой
	// записи. Убрано намеренно — теперь такое расхождение формы с моделью ловит `tsc`.
	phone?: string;
	country?: number | string | null;
	website?: string;
	email?: string;
	logo?: string | null;
	created_at?: string;
	company_types?: string[];
	/** Запись типов компании — по КОДАМ (Rule 2). Читается через `company_types`. */
	types?: string[];
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
	// D2 document theme (Odoo Document Layout model) — one theme drives ALL the company's PDFs.
	secondary_color?: string;
	layout_preset?: DocumentLayoutPreset;
	font_family?: DocumentFontFamily;
	// КП «фирменный бланк» (spec-kp-blank): cover letter + bank-in-header toggle.
	cover_letter_text?: string;
	contract_acceptance_text?: string;
	contract_liability_text?: string;
	contract_extra_terms_text?: string;
	act_closing_text?: string;
	show_cover_letter?: boolean;
	/** Что напечатается при включённом наследовании — считает сервер той же функцией, что и печать. */
	inherited_preview?: {
		legal_name?: string;
		inn?: string;
		legal_address?: string;
		bank_details?: string;
	} | null;
	show_bank_in_header?: boolean;
	use_company_defaults?: boolean;
	// P3 layout toggles — what the seller shows on its documents.
	show_logo?: boolean;
	show_lead_time?: boolean;
	show_fx_note?: boolean;
	created_at?: string;
	updated_at?: string;
}

// Mirror backend CompanyDocumentProfile.LAYOUT_CHOICES / FONT_CHOICES (compare by code, Rule 2).
export type DocumentLayoutPreset = 'light' | 'boxed' | 'bold' | 'striped';
export type DocumentFontFamily = 'sans' | 'serif';
// The sample-document kinds the Document-Layout preview can render (mirror backend PREVIEW_DOC_TYPES).
export type DocumentPreviewType = 'KP' | 'CT' | 'INV' | 'ACT' | 'DOC';

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
	/** Машинный срок оплаты счёта, дней — от него считается напоминание. Пусто = умолчание. */
	payment_terms_days?: number | null;
	// КП «фирменный бланк» defaults (spec-kp-blank): feed the dynamic «Условия поставки» block.
	// ВНИМАНИЕ: `default_payment_terms` — ТЕКСТ для бланка («100% предоплата»), не число.
	default_payment_terms?: string;
	default_warranty_months?: number | null;
	/** Политика каталога (M1-ERP-07): видимость цен по умолчанию и порог публикации, %. */
	catalog_price_visibility?: 'cabinet' | 'on_request';
	catalog_publish_threshold?: number;
	/** Политика курса ЦБ (M1-ERP-09): допустимый возраст курса, дней (1..90). */
	fx_rate_max_age_days?: number;
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
	payment_terms_days?: number | null;
	default_payment_terms?: string;
	default_warranty_months?: number | null;
	catalog_price_visibility?: 'cabinet' | 'on_request';
	catalog_publish_threshold?: number;
	fx_rate_max_age_days?: number;
	doc_number_prefix?: string;
}

export interface UserMembership {
	id: number;
	company: number;
	company_name?: string;
	role?: number | null;
	role_code?: string;
	role_name?: string;
	/** Роли бэк-офиса участника (M1-ERP-05). */
	company_roles?: number[];
	company_roles_data?: { id: number; code: string; name: string; is_system: boolean }[];
	is_primary?: boolean;
	is_active?: boolean;
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
	/** Администратор ERP («Администратор» в CRM): все права без ролей (M1-ERP-05). */
	is_superuser?: boolean;
	preferences?: { language?: string; theme?: string };
	memberships?: UserMembership[];
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
	/** Обойти постраничку и вернуть весь список — операторские реестры без пагинации в UI. */
	fetchAll?: boolean;
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
			return fetchAllPages<Company>('accounts/companies/', query);
		}
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
	/** Архив вместо удаления (паттерн Odoo Archive): компания уходит из оборота, история цела. */
	archiveCompany: async (id: number, reason: string) => {
		const response = await apiClient.post(`accounts/companies/${id}/archive/`, { reason });
		return response.data;
	},
	unarchiveCompany: async (id: number) => {
		const response = await apiClient.post(`accounts/companies/${id}/unarchive/`);
		return response.data;
	},
	deleteCompany: async (id: number) => {
		await apiClient.delete(`accounts/companies/${id}/`);
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
	// Live preview: a SAMPLE document of the requested kind rendered as HTML with the company's
	// profile + UNSAVED draft theme overrides (WYSIWYG, Odoo Document-Layout wizard model).
	// Shown in an iframe on the document-settings panel; re-fired on every draft change (debounced).
	previewCompanyDocumentProfile: async (
		companyId: number,
		payload: { doc_type: DocumentPreviewType; draft?: Partial<CompanyDocumentProfile> },
	): Promise<string> => {
		const response = await apiClient.post(
			`accounts/companies/${companyId}/document-profile/preview/`,
			payload,
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
	// Admin specific endpoints
	getUsers: async (params?: UserFilterParams) => {
		// Операторский реестр показывает список ЦЕЛИКОМ и печатает по нему счётчики, а страницы
		// в интерфейсе нет: без обхода `next` оператор видел ровно первые 20 записей и плашку
		// «Всего 20», хотя в базе их было 24 — вместе с ним самим и владельцем стенда. Тот же
		// обход, что у `getCompanies`; размеры операторских справочников это позволяют.
		if (params?.fetchAll) {
			const query = { ...params };
			delete query.fetchAll;
			return (await fetchAllPages<User>('accounts/users/', query)).map(normalizeUser);
		}
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

	// ─── System Roles (admin) ──────────────────────────────────────────
	getSystemRoles: async () => {
		const response = await apiClient.get<{ code: string; name: string }[]>('accounts/system-roles/');
		return response.data;
	},

	// ─── Workspace Roles ───────────────────────────────────────────────
	// S3 (P2): Company Admin removes a member from the company. Never-orphan on the
	// backend → CANNOT_REMOVE_LAST_COMPANY_ADMIN. `member_id` is the CompanyMember pk.
	removeMember: async (companyId: number, memberId: number) => {
		const response = await apiClient.post<{ removed: boolean; member_id: number }>(
			`accounts/companies/${companyId}/remove-member/`,
			{ member_id: memberId },
		);
		return response.data;
	},
	// S3 (P8): Company Admin activates / deactivates a member's account. Never-orphan
	// (sole admin) and self-deactivation guards live on the backend.
	toggleMemberActive: async (companyId: number, memberId: number) => {
		const response = await apiClient.post<{ member_id: number; user_id: number; is_active: boolean }>(
			`accounts/companies/${companyId}/toggle-member-active/`,
			{ member_id: memberId },
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
	/** Полный набор ролей сотрудника (M1-ERP-05: несколько ролей, права складываются). */
	assignMemberRoles: async (payload: { member_id: number; role_ids: number[] }) => {
		const response = await apiClient.post<{ member_id: number; role_ids: number[] }>(
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
};

// ─── Types ──────────────────────────────────────────────────────────────

export interface CompanyRole {
	id: number;
	/** Код системной роли (`BackofficeRoleCode`: CALCULATION, HEAD…); пусто у своих ролей. */
	code: string;
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
