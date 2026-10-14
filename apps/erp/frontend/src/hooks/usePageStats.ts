import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { dashboardApi } from '../api/dashboardApi';

export const usePageStats = () => useQuery({
  queryKey: ['page-stats'],
  queryFn: dashboardApi.getPageStats,
  staleTime: 60_000,
  gcTime: 5 * 60_000,
});

// Wave I-2 — recent documents feed for the dashboard widget (quotes/contracts/invoices/
// acts/generated). Invalidated by document & billing mutations so the widget stays fresh.
export const useRecentDocuments = (limit = 8) => useQuery({
  queryKey: ['recent-documents', limit],
  queryFn: () => dashboardApi.getRecentDocuments(limit),
  staleTime: 60_000,
  gcTime: 5 * 60_000,
});

// Global document search for the company command palette (Cmd+K). The calling component
// debounces `query`; the hook only fires once the trimmed term reaches 2 chars and keeps the
// previous results visible while the next term loads (no flicker between keystrokes).
export const useSearchDocuments = (query: string, limit = 8) => {
  const term = query.trim();
  return useQuery({
    queryKey: ['search-documents', term, limit],
    queryFn: () => dashboardApi.searchDocuments(term, limit),
    enabled: term.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    gcTime: 5 * 60_000,
  });
};
