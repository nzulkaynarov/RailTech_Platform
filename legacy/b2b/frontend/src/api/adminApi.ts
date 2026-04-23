import { apiClient } from './client';

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
  level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR';
  reason: string;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  user_id: number | null;
  user_email: string | null;
  user_name: string;
  timestamp: string;
}

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
