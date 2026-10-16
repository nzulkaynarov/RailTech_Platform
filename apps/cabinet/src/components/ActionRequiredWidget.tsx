import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AlertCircle, CheckCircle2, ClipboardCheck, FileSignature, FileText, Receipt } from 'lucide-react';

import { useActs, useContracts, useInvoices, useQuotes } from '@/api/queries';
import { ToneBadge } from '@/components/StatusBadge';
import { Card, CardContent } from '@/components/ui/card';
import { formatMoney } from '@/lib/format';
import { invoiceViews } from '@/lib/invoice';

/**
 * Виджет «Требует вашего решения» (M2-CAB-04, бенчмарк Odoo/ERPNext: клиент видит «что от меня ждут»).
 * Агрегирует:
 *   - КП со статусом sent (ждут рассмотрения клиентом);
 *   - Договоры sent/issued без подписи клиента;
 *   - Счета с неоплаченным остатком;
 *   - Акты issued, требующие приёмки или возврата.
 */
export function ActionRequiredWidget() {
  const { t } = useTranslation();
  const quotesQuery = useQuotes();
  const contractsQuery = useContracts();
  const invoicesQuery = useInvoices();
  const actsQuery = useActs();

  const isPending =
    quotesQuery.isPending || contractsQuery.isPending || invoicesQuery.isPending || actsQuery.isPending;
  const isError =
    quotesQuery.isError || contractsQuery.isError || invoicesQuery.isError || actsQuery.isError;

  if (isPending || isError) return null;

  const pendingQuotes = (quotesQuery.data ?? []).filter((q) => q.status === 'sent');
  const pendingContracts = (contractsQuery.data ?? []).filter(
    (c) => (c.status === 'sent' || c.status === 'signed_by_company') && !c.signed_by_client_at,
  );
  const views = invoiceViews(invoicesQuery.data ?? []);
  const pendingInvoices = (invoicesQuery.data ?? []).filter((inv) => {
    const view = views.get(inv.id);
    if (!view || inv.status === 'paid') return false;
    const amount = Number(view.remaining?.amount ?? 0);
    return amount > 0;
  });
  const pendingActs = (actsQuery.data ?? []).filter((a) => a.status === 'issued');

  const totalActions =
    pendingQuotes.length + pendingContracts.length + pendingInvoices.length + pendingActs.length;

  if (totalActions === 0) {
    return (
      <div className="mb-6 flex items-center gap-3 rounded-lg border border-dashed bg-card/60 p-3.5 text-sm text-muted-foreground">
        <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden="true" />
        <span>{t('widgets.actionRequired.allClear')}</span>
      </div>
    );
  }

  return (
    <section role="region" aria-label={t('widgets.actionRequired.title')} className="mb-6 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <h2 id="action-required-heading" className="text-sm font-semibold tracking-tight text-foreground">
          {t('widgets.actionRequired.title')}
        </h2>
        <ToneBadge tone="warning">{totalActions}</ToneBadge>
      </div>

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
        {pendingQuotes.map((quote) => (
          <Card
            key={`quote-${quote.id}`}
            className="group relative border-border bg-card transition-colors hover:border-primary/50 hover:bg-accent/40"
          >
            <CardContent className="flex flex-col gap-1.5 p-3.5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className="flex items-center gap-1 font-medium text-warning">
                  <FileText className="size-3.5" aria-hidden="true" />
                  {t('widgets.actionRequired.quoteBadge')}
                </span>
                <span className="font-semibold text-foreground">{formatMoney(quote.total)}</span>
              </div>
              <p className="text-sm font-medium text-foreground">
                <Link
                  to={`/quotes/${quote.id}`}
                  className="rounded-sm outline-none after:absolute after:inset-0 hover:underline focus-visible:after:ring-2 focus-visible:after:ring-ring"
                >
                  {t('pages.quotes.numberVersion', { number: quote.number, version: quote.version })}
                </Link>
              </p>
              <span className="text-xs text-muted-foreground">{t('widgets.actionRequired.reviewQuote')}</span>
            </CardContent>
          </Card>
        ))}

        {pendingContracts.map((contract) => (
          <Card
            key={`contract-${contract.id}`}
            className="group relative border-border bg-card transition-colors hover:border-primary/50 hover:bg-accent/40"
          >
            <CardContent className="flex flex-col gap-1.5 p-3.5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className="flex items-center gap-1 font-medium text-info">
                  <FileSignature className="size-3.5" aria-hidden="true" />
                  {t('widgets.actionRequired.contractBadge')}
                </span>
                <AlertCircle className="size-3.5 text-info" aria-hidden="true" />
              </div>
              <p className="text-sm font-medium text-foreground">
                <Link
                  to="/contracts"
                  className="rounded-sm outline-none after:absolute after:inset-0 hover:underline focus-visible:after:ring-2 focus-visible:after:ring-ring"
                >
                  {contract.number}
                </Link>
              </p>
              <span className="text-xs text-muted-foreground">{t('widgets.actionRequired.signContract')}</span>
            </CardContent>
          </Card>
        ))}

        {pendingInvoices.map((inv) => {
          const view = views.get(inv.id);
          return (
            <Card
              key={`inv-${inv.id}`}
              className="group relative border-border bg-card transition-colors hover:border-primary/50 hover:bg-accent/40"
            >
              <CardContent className="flex flex-col gap-1.5 p-3.5">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span className="flex items-center gap-1 font-medium text-warning">
                    <Receipt className="size-3.5" aria-hidden="true" />
                    {t('widgets.actionRequired.invoiceBadge')}
                  </span>
                  <span className="font-semibold text-foreground">{formatMoney(view?.remaining)}</span>
                </div>
                <p className="text-sm font-medium text-foreground">
                  <Link
                    to="/invoices"
                    className="rounded-sm outline-none after:absolute after:inset-0 hover:underline focus-visible:after:ring-2 focus-visible:after:ring-ring"
                  >
                    {inv.number}
                  </Link>
                </p>
                <span className="text-xs text-muted-foreground">{t('widgets.actionRequired.payInvoice')}</span>
              </CardContent>
            </Card>
          );
        })}

        {pendingActs.map((act) => (
          <Card
            key={`act-${act.id}`}
            className="group relative border-border bg-card transition-colors hover:border-primary/50 hover:bg-accent/40"
          >
            <CardContent className="flex flex-col gap-1.5 p-3.5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className="flex items-center gap-1 font-medium text-info">
                  <ClipboardCheck className="size-3.5" aria-hidden="true" />
                  {t('widgets.actionRequired.actBadge')}
                </span>
                <AlertCircle className="size-3.5 text-info" aria-hidden="true" />
              </div>
              <p className="text-sm font-medium text-foreground">
                <Link
                  to="/acts"
                  className="rounded-sm outline-none after:absolute after:inset-0 hover:underline focus-visible:after:ring-2 focus-visible:after:ring-ring"
                >
                  {act.number}
                </Link>
              </p>
              <span className="text-xs text-muted-foreground">{t('widgets.actionRequired.acceptAct')}</span>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}
