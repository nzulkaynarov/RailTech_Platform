import { apiClient } from './client';
import { fetchAllPages } from './fetchAllPages';

export type AdminQueueSeverity = 'critical' | 'warning' | 'info';

export interface AdminQueueItem {
  queue_type:
    | 'kyc_pending'
    | 'role_application'
    | 'subscription_past_due'
    | 'subscription_expiring'
    | 'invoice_overdue'
    | 'support_urgent';
  entity_type: string;
  entity_id: number;
  title: string;
  subtitle: string;
  severity: AdminQueueSeverity;
  created_at: string | null;
  age: string;
  actions: string[];
  link: string;
}

export interface AdminQueueResponse {
  count: number;
  totals: Record<string, number>;
  items: AdminQueueItem[];
}

export interface AdminPulseDay {
  date: string;
  count: number;
  value: string;
}

export interface AdminPulseResponse {
  period: string;
  days: number;
  companies: AdminPulseDay[];
  deals: AdminPulseDay[];
  quotes_signed_value: AdminPulseDay[];
  mrr: string;
  active_subscriptions: number;
}

export interface AdminSearchItem {
  id: number;
  title: string;
  subtitle: string;
  link: string;
}

export interface AdminSearchGroup {
  type: 'company' | 'user' | 'deal' | 'offer' | 'support_ticket';
  label: string;
  items: AdminSearchItem[];
}

export interface AdminSearchResponse {
  q: string;
  groups: AdminSearchGroup[];
}

export interface AdminActivityEntry {
  id: number;
  action: string;
  detail: string;
  /**
   * Структурированное событие: интерфейс локализует `activity.<event_code>`, а `action`/`detail`
   * остаются русским запасным вариантом для старых записей. Эндпоинт отдавал эти поля с самого
   * начала — тип о них просто не знал, и локализация была недоступна.
   */
  event_code?: string | null;
  event_params?: Record<string, unknown> | null;
  level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR';
  reason: string;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  user_id: number | null;
  user_email: string | null;
  user_name: string;
  timestamp: string;
}

/** Access-log entry: a break-glass grant or a force-override action (ADR-0004 G2). */
export interface AdminAccessLogEntry {
  id: number;
  action: string;
  detail: string;
  event_code?: string;
  event_params?: Record<string, unknown>;
  level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR';
  reason: string;
  entity_type: string;
  entity_id: number | null;
  user_email: string | null;
  user_name: string;
  timestamp: string;
  expires_at: string | null;
  is_break_glass: boolean;
  /** Действие платформенного админа за арендатора — маркер `[FORCE_ADMIN]`. */
  is_force_override: boolean;
  is_active: boolean;
}

/* ─── Email templates ───────────────────────────────────────────────── */

export type EmailTemplateKey =
  | 'setup_password'
  | 'invite_member'
  | 'kyc_verified'
  | 'quote_sent'
  | 'reset_password'
  | 'role_application_approved'
  | 'role_application_rejected';

export interface EmailTemplate {
  id: number;
  key: string;
  subject: string;
  html_body: string;
  text_body: string;
  available_variables: string;
  is_active: boolean;
  updated_by: number | null;
  updated_by_email: string | null;
  updated_at: string | null;
}

export interface EmailTemplateDraft {
  key: string;
  subject: string;
  html_body: string;
  text_body: string;
  available_variables: string;
  is_active: boolean;
}

export interface EmailTemplatePreview {
  key: string;
  subject: string;
  text_body: string;
  html_body: string;
  context_used: Record<string, unknown>;
}

export interface EmailTemplateTestSendResult {
  status: 'SENT' | 'FAILED';
  email_log_id: number | null;
  to_email: string;
}

export const emailTemplatesApi = {
  list: async () => {
    // Эндпоинт ПАГИНИРОВАН (schema.json: PaginatedEmailTemplateList), а метод отдавал объект
    // страницы как массив — страница падала на `templates.filter` и уносила с собой всю SPA
    // («n?.filter is not a function»). Разворачиваем так же, как соседние методы файла.
    const res = await apiClient.get<EmailTemplate[] | { results: EmailTemplate[] }>('admin/email-templates/');
    return Array.isArray(res.data) ? res.data : res.data.results;
  },
  create: async (data: EmailTemplateDraft) => {
    const res = await apiClient.post<EmailTemplate>('admin/email-templates/', data);
    return res.data;
  },
  update: async (id: number, data: Partial<EmailTemplateDraft>) => {
    const res = await apiClient.patch<EmailTemplate>(`admin/email-templates/${id}/`, data);
    return res.data;
  },
  remove: async (id: number) => {
    await apiClient.delete(`admin/email-templates/${id}/`);
  },
  preview: async (id: number, context?: Record<string, unknown>) => {
    const res = await apiClient.post<EmailTemplatePreview>(
      `admin/email-templates/${id}/preview/`,
      { context },
    );
    return res.data;
  },
  testSend: async (id: number, toEmail: string, context?: Record<string, unknown>) => {
    const res = await apiClient.post<EmailTemplateTestSendResult>(
      `admin/email-templates/${id}/test-send/`,
      { to_email: toEmail, context },
    );
    return res.data;
  },
};

/* ─── Operator roles (ADR-0004 G1) ──────────────────────────────────── */

/** A platform-operator sub-role with its capability set. */
export interface OperatorRole {
  id: number;
  code: string;
  name: string;
  permissions: string[];
  is_system: boolean;
  description: string;
  operator_count: number;
}

/** Mutable fields when creating/updating an operator role. */
export interface OperatorRoleDraft {
  name: string;
  permissions: string[];
  description: string;
}

export interface OperatorPermissionDef {
  code: string;
  label: string;
  label_en: string;
}

export interface OperatorPermissionGroup {
  key: string;
  label: string;
  label_en: string;
  permissions: OperatorPermissionDef[];
}

export const operatorRolesApi = {
  list: async () => {
    // ModelViewSet — unwrap DRF pagination defensively (plain array or {results}).
    const res = await apiClient.get<OperatorRole[] | { results: OperatorRole[] }>(
      'admin/operator-roles/',
    );
    return Array.isArray(res.data) ? res.data : res.data.results;
  },
  create: async (data: OperatorRoleDraft) => {
    const res = await apiClient.post<OperatorRole>('admin/operator-roles/', data);
    return res.data;
  },
  update: async (id: number, data: OperatorRoleDraft) => {
    const res = await apiClient.put<OperatorRole>(`admin/operator-roles/${id}/`, data);
    return res.data;
  },
  remove: async (id: number) => {
    await apiClient.delete(`admin/operator-roles/${id}/`);
  },
  assign: async (userId: number, roleId: number | null) => {
    const res = await apiClient.post<{ user_id: number; operator_role_id: number | null }>(
      'admin/operator-roles/assign/',
      { user_id: userId, role_id: roleId },
    );
    return res.data;
  },
  permissionCatalog: async () => {
    // Backend returns { groups: [...] } — unwrap to the array the UI maps over.
    const res = await apiClient.get<{ groups: OperatorPermissionGroup[] }>(
      'admin/operator-permissions/',
    );
    return res.data.groups;
  },
};

/* ─── Company entitlements — Move 4 monetization control plane (ADR-0006) ─── */

export interface CompanyEntitlement {
  id: number;
  company: number;
  company_name: string;
  company_inn: string;
  feature_key: string;
  access: string;           // ENABLED | DISABLED | DEMO (codes from the backend choices)
  access_display: string;
  limit: number | null;
  credits: number | null;
  expires_at: string | null;
  note: string;
  is_granted: boolean;
  created_at?: string;
  updated_at?: string;
}

/** Mutable fields when granting / editing an entitlement. */
export interface CompanyEntitlementDraft {
  company: number;
  feature_key: string;
  access: string;
  limit?: number | null;
  credits?: number | null;
  expires_at?: string | null;
  note?: string;
}

export interface EntitlementChoice {
  value: string;
  label: string;
}

export const entitlementsApi = {
  // Backend-driven option lists (FeatureKey + access states) — no hard-coded enums in the FE.
  choices: async () => {
    const res = await apiClient.get<{ feature_keys: EntitlementChoice[]; access_states: EntitlementChoice[] }>(
      'admin/entitlements/choices/',
    );
    return res.data;
  },
  // Права-энтайтлменты — плоскость монетизации (ADR-0006 §3): строка здесь включает или гасит
  // платную возможность у конкретной компании и ПЕРЕБИВАЕТ подписку. Первая страница вместо
  // всего списка означала, что выданное 21-м промо не увидит и не отзовёт никто.
  list: async (params?: { company?: number; feature_key?: string; access?: string; search?: string }) =>
    fetchAllPages<CompanyEntitlement>('admin/entitlements/', params as Record<string, unknown>),
  create: async (data: CompanyEntitlementDraft) => {
    const res = await apiClient.post<CompanyEntitlement>('admin/entitlements/', data);
    return res.data;
  },
  update: async (id: number, data: Partial<CompanyEntitlementDraft>) => {
    const res = await apiClient.patch<CompanyEntitlement>(`admin/entitlements/${id}/`, data);
    return res.data;
  },
  remove: async (id: number) => {
    await apiClient.delete(`admin/entitlements/${id}/`);
  },
};

export const adminApi = {
  getQueue: async (params?: { queue_type?: string; limit?: number }) => {
    const res = await apiClient.get<AdminQueueResponse>('admin/queue/', { params });
    return res.data;
  },
  getPulse: async (period: '7d' | '30d' | '90d' = '30d') => {
    const res = await apiClient.get<AdminPulseResponse>('admin/pulse/', {
      params: { period },
    });
    return res.data;
  },
  search: async (q: string, perGroup = 5) => {
    if (!q || q.trim().length < 2) {
      return { q, groups: [] } as AdminSearchResponse;
    }
    const res = await apiClient.get<AdminSearchResponse>('admin/search/', {
      params: { q, per_group: perGroup },
    });
    return res.data;
  },
  getActivity: async (entityType: string, entityId: number | string, limit = 100) => {
    const res = await apiClient.get<{
      count: number;
      items: AdminActivityEntry[];
    }>('admin/activity/', {
      params: { entity_type: entityType, entity_id: entityId, limit },
    });
    return res.data;
  },
  /** Access log feed: break-glass grants + force-override actions (G2). */
  getAccessLog: async (limit = 100) => {
    const res = await apiClient.get<{
      count: number;
      items: AdminAccessLogEntry[];
    }>('admin/access-log/', { params: { limit } });
    return res.data;
  },
  /** Open a reason-required, time-boxed break-glass grant (G2). */
  openBreakGlass: async (entityType: string, entityId: number, reason: string, minutes?: number) => {
    const res = await apiClient.post('admin/break-glass/', {
      entity_type: entityType,
      entity_id: entityId,
      reason,
      ...(minutes ? { minutes } : {}),
    });
    return res.data;
  },
  bulkVerifyKYC: async (ids: number[], level = 'L2_VERIFIED', reason = '') => {
    const res = await apiClient.post<{
      approved: number;
      skipped: { company_id: number; name: string; error: string }[];
    }>('accounts/companies/bulk-verify-kyc/', { ids, level, reason });
    return res.data;
  },
  bulkSetSubscriptionStatus: async (
    ids: number[],
    status: 'ACTIVE' | 'SUSPENDED',
    reason = '',
  ) => {
    const res = await apiClient.post<{ affected: number; target: string }>(
      'accounts/subscriptions/bulk-set-status/',
      { ids, status, reason },
    );
    return res.data;
  },
};
