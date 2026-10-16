import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query';

import * as portal from './portal';

/**
 * React Query над портальным API — единственное хранилище данных экранов (CLAUDE.md §3).
 * Ключи — по эндпоинту; после действия (принять, подписать, вернуть…) мутация кладёт ответ ERP
 * в кэш и инвалидирует связанные списки: ERP — источник правды, Cabinet ничего не досчитывает.
 */
export const keys = {
  requests: ['requests'] as const,
  request: (id: number) => ['requests', id] as const,
  quotes: ['quotes'] as const,
  quote: (id: number) => ['quotes', id] as const,
  contracts: ['contracts'] as const,
  invoices: ['invoices'] as const,
  acts: ['acts'] as const,
  deliveries: ['deliveries'] as const,
  documents: (params: portal.DocumentsQuery = {}) => ['documents', params] as const,
  catalog: (params: portal.CatalogQuery) => ['catalog', params] as const,
  catalogCategories: ['catalog', 'categories'] as const,
  catalogItem: (id: number) => ['catalog', 'item', id] as const,
  company: ['company'] as const,
  team: ['team'] as const,
};

export const useRequests = () => useQuery({ queryKey: keys.requests, queryFn: portal.listRequests });
export const useRequest = (id: number) =>
  useQuery({ queryKey: keys.request(id), queryFn: () => portal.getRequest(id), enabled: Number.isFinite(id) });
export const useQuotes = () => useQuery({ queryKey: keys.quotes, queryFn: portal.listQuotes });
export const useQuote = (id: number) =>
  useQuery({ queryKey: keys.quote(id), queryFn: () => portal.getQuote(id), enabled: Number.isFinite(id) });
export const useContracts = () => useQuery({ queryKey: keys.contracts, queryFn: portal.listContracts });
export const useInvoices = () => useQuery({ queryKey: keys.invoices, queryFn: portal.listInvoices });
export const useActs = () => useQuery({ queryKey: keys.acts, queryFn: portal.listActs });
export const useDeliveries = () => useQuery({ queryKey: keys.deliveries, queryFn: portal.listDeliveries });
export const useDocuments = (params: portal.DocumentsQuery = {}) =>
  useQuery({ queryKey: keys.documents(params), queryFn: () => portal.listDocuments(params) });
export const useCatalogCategories = () =>
  useQuery({ queryKey: keys.catalogCategories, queryFn: portal.listCatalogCategories });
export const useCatalog = (params: portal.CatalogQuery, enabled = true) =>
  useQuery({
    queryKey: keys.catalog(params),
    queryFn: () => portal.listCatalog(params),
    placeholderData: keepPreviousData,
    enabled,
  });
export const useCatalogItem = (id: number) =>
  useQuery({ queryKey: keys.catalogItem(id), queryFn: () => portal.getCatalogItem(id), enabled: Number.isFinite(id) });
export const useCompany = () => useQuery({ queryKey: keys.company, queryFn: portal.getCompany });
export const useTeam = () => useQuery({ queryKey: keys.team, queryFn: portal.listTeam });

/** Мутация, после которой связанные списки перечитываются у ERP. */
function useInvalidatingMutation<TVars, TData>(
  mutationFn: (vars: TVars) => Promise<TData>,
  invalidate: QueryKey[],
  onData?: (data: TData, client: ReturnType<typeof useQueryClient>) => void,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: (data) => {
      onData?.(data, client);
      for (const queryKey of invalidate) void client.invalidateQueries({ queryKey });
    },
  });
}

export const useCreateRequest = () => useInvalidatingMutation(portal.createRequest, [keys.requests]);
export const useUploadFile = () => useMutation({ mutationFn: portal.uploadFile });

/** После акцепта ERP сам создаёт договор (BUSINESS §4, шаг 6) — перечитываем договоры и документы. */
export const useAcceptQuote = (id: number) =>
  useInvalidatingMutation(
    (code: string) => portal.acceptQuote(id, code),
    [keys.quotes, keys.contracts, keys.requests, ['documents']],
    (quote, client) => client.setQueryData(keys.quote(id), quote),
  );
export const useRejectQuote = (id: number) =>
  useInvalidatingMutation(
    (reason: string) => portal.rejectQuote(id, reason),
    [keys.quotes, keys.requests],
    (quote, client) => client.setQueryData(keys.quote(id), quote),
  );

export const useSignContract = () => useInvalidatingMutation(portal.signContract, [keys.contracts, ['documents']]);
export const useAcceptAct = () => useInvalidatingMutation(portal.acceptAct, [keys.acts]);
export const useReturnAct = () =>
  useInvalidatingMutation(({ id, reason }: { id: number; reason: string }) => portal.returnAct(id, reason), [keys.acts]);

export const useUpdateCompany = () =>
  useInvalidatingMutation(portal.updateCompany, [['me']], (company, client) => client.setQueryData(keys.company, company));
export const useInviteTeamMember = () => useInvalidatingMutation(portal.inviteTeamMember, [keys.team]);
