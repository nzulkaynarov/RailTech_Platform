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
  clients: { total: number };
  products: { total: number; published: number; categories: number; equipment_groups: number; offers: number };
  analytics: { conversion: string; avg_deal: string; pipeline: string; win_rate: string };
  admin_users: { total: number; admins: number; managers: number; employees: number };
  imports: { total: number; attachments: number };
  notifications_unread: number;
}

// Wave I-2 — виджет «Недавние документы» (та же форма строки у поиска документов ⌘K).
// Маршрута здесь НЕТ намеренно: раньше сервер отдавал готовый `hash`, но про гейты SPA он не
// знает — ссылка на акт и КП была продавцовской и уводила клиента в отказ (аудит UI, U1).
// `type` + `id` + `deal` — всё, что нужно `lib/documentRoute`, чтобы посчитать маршрут по
// стороне зрителя.
export interface RecentDocument {
  type: 'quote' | 'contract' | 'invoice' | 'act' | 'generated' | 'receipt' | 'delivery_note';
  id: number;
  label: string;
  status_code: string | null;
  date: string;
  deal: number | null;
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
  // Global document search for the company command palette (Cmd+K). Returns the same
  // Форма строки — та же `RecentDocument` (маршрут считает клиент, см. комментарий выше).
  // q shorter than 2 chars yields an empty result set on the backend.
  searchDocuments: async (query: string, limit = 8): Promise<RecentDocument[]> => {
    const response = await apiClient.get<{ results: RecentDocument[] }>(
      `crm/analytics/search-documents/?q=${encodeURIComponent(query)}&limit=${limit}`,
    );
    return response.data.results;
  },
  getPageStats: async (): Promise<PageStats> => {
    const response = await apiClient.get<PageStats>('analytics/page-stats/');
    return response.data;
  },
};
