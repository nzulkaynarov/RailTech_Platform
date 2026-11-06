import {
  useActs,
  useCompanyPartnerApplication,
  useContracts,
  useDeliveries,
  useInvoices,
  usePartnerProducts,
  useQuotes,
} from '@/api/queries';
import { useNow } from '@/hooks/useNow';
import { useUnread } from '@/hooks/useUnread';
import { invoiceViews } from '@/lib/invoice';
import { quoteAwaitsDecision } from '@/lib/quotes';
import { contractAwaitsClient } from '@/lib/status';
import { useHasModule } from '@/session/useMe';

/**
 * Что ждёт решения клиента или партнёра (виджет «Требует вашего решения», волна J1):
 * - КП `sent`/`viewed` в сроке;
 * - Договоры на согласовании клиента;
 * - Просроченные счета к оплате;
 * - Выпущенные акты к приёмке;
 * - Поставки `delivered`, ожидающие приёмки;
 * - Проект партнёрского договора к согласованию (`contract_sent`);
 * - Карточки товаров партнёра с замечаниями снабжения (`rejected`);
 * - Непрочитанные ответы менеджера в чате.
 */
export function useActionRequired() {
  const now = useNow();
  const unread = useUnread();
  const modules = {
    quotes: useHasModule('quotes'),
    contracts: useHasModule('contracts'),
    invoices: useHasModule('invoices'),
    acts: useHasModule('acts'),
    deliveries: useHasModule('deliveries'),
    myProducts: useHasModule('my_products'),
  };
  const queries = [
    useQuotes({ enabled: modules.quotes }),
    useContracts({ enabled: modules.contracts }),
    useInvoices({ enabled: modules.invoices }),
    useActs({ enabled: modules.acts }),
    useDeliveries({ enabled: modules.deliveries }),
  ] as const;
  const [quotes, contracts, invoices, acts, deliveries] = queries;
  const partnerProductsQuery = usePartnerProducts(
    { status: 'rejected', page_size: 20 },
    { enabled: modules.myProducts },
  );
  const partnerAppQuery = useCompanyPartnerApplication({ enabled: !modules.myProducts });

  const available = Object.values(modules).some(Boolean) || Boolean(partnerAppQuery.data?.has_application);
  const isPending =
    queries.some((query) => query.isPending && query.fetchStatus !== 'idle') ||
    (modules.myProducts && partnerProductsQuery.isPending && partnerProductsQuery.fetchStatus !== 'idle');
  const failed = [
    ...queries.filter((query) => query.isError),
    ...(modules.myProducts && partnerProductsQuery.isError ? [partnerProductsQuery] : []),
  ];
  const views = invoiceViews(invoices.data ?? [], now);

  const awaitingQuotes = (quotes.data ?? []).filter((quote) => quoteAwaitsDecision(quote, now));
  const awaitingContracts = (contracts.data ?? []).filter(
    (contract) => contractAwaitsClient(contract.status) && !contract.signed_by_client_at,
  );
  const overdueInvoices = (invoices.data ?? []).filter((invoice) => Boolean(views.get(invoice.id)?.overdueDays));
  const awaitingActs = (acts.data ?? []).filter((act) => act.status === 'issued');
  const awaitingDeliveries = (deliveries.data ?? []).filter((delivery) => delivery.status === 'delivered');
  const partnerApplicationAwaiting = Boolean(
    partnerAppQuery.data?.has_application && partnerAppQuery.data.status === 'contract_sent',
  );
  const rejectedProducts = (partnerProductsQuery.data?.items ?? []).filter(
    (product) => product.status === 'rejected',
  );

  const total =
    awaitingQuotes.length +
    awaitingContracts.length +
    overdueInvoices.length +
    awaitingActs.length +
    awaitingDeliveries.length +
    (partnerApplicationAwaiting ? 1 : 0) +
    rejectedProducts.length +
    (unread > 0 ? 1 : 0);

  return {
    available,
    isPending,
    error: failed[0]?.error ?? null,
    retry: () => {
      failed.forEach((query) => void query.refetch());
      if (partnerProductsQuery.isError) void partnerProductsQuery.refetch();
    },
    views,
    quotes: awaitingQuotes,
    contracts: awaitingContracts,
    invoices: overdueInvoices,
    acts: awaitingActs,
    deliveries: awaitingDeliveries,
    partnerApplication: partnerAppQuery.data ?? null,
    partnerApplicationAwaiting,
    rejectedProducts,
    unread,
    total,
  };
}

/**
 * Счётчики требующих решения дел по разделам для бейджей навигации (J1).
 */
export function useNavBadges(): Record<string, number> {
  const actions = useActionRequired();
  return {
    '/quotes': actions.quotes.length,
    '/contracts': actions.contracts.length,
    '/invoices': actions.invoices.length,
    '/acts': actions.acts.length,
    '/deliveries': actions.deliveries.length,
    '/my-products': actions.rejectedProducts.length,
    '/company': actions.partnerApplicationAwaiting ? 1 : 0,
    '/messages': actions.unread,
  };
}
