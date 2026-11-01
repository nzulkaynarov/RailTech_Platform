import { useActs, useContracts, useInvoices, useQuotes } from '@/api/queries';
import { useNow } from '@/hooks/useNow';
import { invoiceViews } from '@/lib/invoice';
import { quoteAwaitsDecision } from '@/lib/quotes';
import { contractAwaitsClient } from '@/lib/status';

/**
 * Что ждёт решения клиента (виджет «Требует вашего решения»): КП `sent`/`viewed` в сроке, договоры на согласовании
 * клиента, просроченные счета, выпущенные акты. Те же четыре списка React Query, что у разделов, — экран «Запросы»
 * вызывает хук сам, чтобы показать список одновременно с виджетом, без вставки виджета над готовым списком (K10).
 */
export function useActionRequired() {
  const now = useNow();
  const queries = [useQuotes(), useContracts(), useInvoices(), useActs()] as const;
  const [quotes, contracts, invoices, acts] = queries;
  const isPending = queries.some((query) => query.isPending);
  const failed = queries.filter((query) => query.isError);
  const views = invoiceViews(invoices.data ?? [], now);
  return {
    isPending,
    error: failed[0]?.error ?? null,
    retry: () => failed.forEach((query) => void query.refetch()),
    views,
    quotes: (quotes.data ?? []).filter((quote) => quoteAwaitsDecision(quote, now)),
    contracts: (contracts.data ?? []).filter((contract) => contractAwaitsClient(contract.status) && !contract.signed_by_client_at),
    invoices: (invoices.data ?? []).filter((invoice) => Boolean(views.get(invoice.id)?.overdueDays)),
    acts: (acts.data ?? []).filter((act) => act.status === 'issued'),
  };
}
