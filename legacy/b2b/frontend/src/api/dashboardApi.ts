import { apiClient } from './client';

export interface DashboardStats {
  deals_volume: number;
  deals_volume_change: number;
  active_requests: number;
  active_requests_change: number;
  catalog_items: number;
  catalog_items_change: number;
  clients_count: number;
  clients_count_change: number;
  deals_by_month: { month: string; value: number }[];
  activity_by_day: { day: string; count: number }[];
  top_products: { id: string; name: string; quantity: number; category: string }[];
  counterparties: { manufacturers: number; buyers: number; intermediaries: number };
  request_completion: number;
  request_completion_goal: number;
  deals_in_progress: number;
  quotes_received: number;
  deals_completed: number;
}

export interface PageStats {
  sourcing: { total: number; new: number; in_progress: number; completed: number };
  deals: { total: number; active: number; quote_sent: number; closed_won: number };
  quotes: { drafts: number; sent: number; approved: number; under_review: number; total_amount: string; pipeline: string };
  clients: { total: number; verified: number; awaiting_kyc: number; unverified: number };
  products: { total: number; published: number; categories: number; equipment_groups: number; offers: number };
  analytics: { conversion: string; avg_deal: string; pipeline: string; win_rate: string };
  analytics_buyer: { spend_period: string; active_requests: number };
  my_requests: { active: number; quote_received: number; contract: number; completed: number };
  admin_users: { total: number; admins: number; managers: number; employees: number };
  imports: { total: number; attachments: number };
  notifications_unread: number;
}

export interface PlatformDashboard {
  users: { total: number; active: number; new_7d: number; admins: number };
  companies: {
    total: number;
    by_type: { BUYER: number; SELLER: number; MANUFACTURER: number };
    pending_kyc: number;
    verified: number;
  };
  deals: {
    total: number;
    active: number;
    won: number;
    lost: number;
    by_stage: { stage__code: string; stage__name: string; count: number }[];
    pipeline_value: string;
    won_value: string;
  };
  subscriptions: {
    active: number;
    trial: number;
    past_due: number;
    suspended: number;
    expiring_7d: number;
  };
  attention: {
    kyc: number;
    role_applications: number;
    subscriptions_past_due: number;
    subscriptions_expiring_7d: number;
    overdue_invoices: number;
  };
  recent_activity: {
    id: number;
    action: string;
    detail: string;
    event_code?: string;
    event_params?: Record<string, unknown>;
    level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR';
    user_email: string | null;
    timestamp: string;
  }[];
}

// Wave I-2 — «Недавние документы» dashboard widget. The backend returns a ready-to-use
// SPA deep-link in `hash` (e.g. `deal-quote/5`, `invoices?open=3`, `other-documents`), so
// the widget never has to reconstruct navigation targets per document type.
export interface RecentDocument {
  type: 'quote' | 'contract' | 'invoice' | 'act' | 'generated';
  id: number;
  label: string;
  status_code: string | null;
  date: string;
  deal: number | null;
  hash: string;
}

export const dashboardApi = {
  getStats: async (period?: string): Promise<DashboardStats> => {
    const url = period ? `crm/analytics/dashboard/?period=${period}` : 'crm/analytics/dashboard/';
    const response = await apiClient.get<DashboardStats>(url);
    return response.data;
  },
  getRecentDocuments: async (limit = 8): Promise<RecentDocument[]> => {
    const response = await apiClient.get<{ results: RecentDocument[] }>(
      `crm/analytics/recent-documents/?limit=${limit}`,
    );
    return response.data.results;
  },
  getPageStats: async (): Promise<PageStats> => {
    const response = await apiClient.get<PageStats>('analytics/page-stats/');
    return response.data;
  },
  getPlatformDashboard: async (): Promise<PlatformDashboard> => {
    const response = await apiClient.get<PlatformDashboard>('analytics/platform-dashboard/');
    return response.data;
  },
};
