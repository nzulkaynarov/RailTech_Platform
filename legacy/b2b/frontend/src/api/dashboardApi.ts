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
  sourcing_match: { unrecognized: number; matches: number; need_review: number; accuracy: string };
  deals: { total: number; active: number; quote_sent: number; closed_won: number };
  quotes: { drafts: number; sent: number; approved: number; under_review: number; total_amount: string; pipeline: string };
  clients: { total: number; verified: number; awaiting_kyc: number; unverified: number };
  products: { total: number; published: number; categories: number; equipment_groups: number; offers: number };
  production: { active: number; awaiting_response: number; responded: number; overdue: number };
  production_schedule: { active_orders: number; completed: number; delayed: number; next_week: number };
  analytics: { conversion: string; avg_deal: string; pipeline: string; win_rate: string };
  analytics_buyer: { spend_period: string; savings: string; active_requests: number };
  integrations: { connected: number; pending: number; available_apis: number; synced_records: number };
  my_requests: { active: number; quote_received: number; contract: number; completed: number };
  logistics: { in_transit: number; customs: number; delivered: number; delays: number };
  admin_users: { total: number; admins: number; managers: number; employees: number };
  imports: { total: number; attachments: number };
  notifications_unread: number;
}

export const dashboardApi = {
  getStats: async (period?: string): Promise<DashboardStats> => {
    const url = period ? `crm/analytics/dashboard/?period=${period}` : 'crm/analytics/dashboard/';
    const response = await apiClient.get<DashboardStats>(url);
    return response.data;
  },
  getPageStats: async (): Promise<PageStats> => {
    const response = await apiClient.get<PageStats>('analytics/page-stats/');
    return response.data;
  },
};
