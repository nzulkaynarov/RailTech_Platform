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
}

export const dashboardApi = {
  getStats: async (period?: string): Promise<DashboardStats> => {
    const url = period ? `crm/analytics/dashboard/?period=${period}` : 'crm/analytics/dashboard/';
    const response = await apiClient.get<DashboardStats>(url);
    return response.data;
  }
};
