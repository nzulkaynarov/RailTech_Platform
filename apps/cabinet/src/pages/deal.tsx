import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Briefcase, Check, FileText } from 'lucide-react';

import type { DealRef } from '@/api/portal';
import { useActs, useContracts, useDeliveries, useDocuments, useInvoices, useQuotes, useRequests } from '@/api/queries';
import { SectionTitle } from '@/components/Details';
import { DocumentButton } from '@/components/DocumentButton';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { ErrorState, ListSkeleton } from '@/components/QueryStates';
import { StatusBadge } from '@/components/StatusBadge';
import { ManagerButton } from '@/components/TelegramLinkButton';
import { Button } from '@/components/ui/button';
import { useNow } from '@/hooks/useNow';
import { formatDate, formatMoney, formatQuantity } from '@/lib/format';
import { dealProgress, type DealProgress } from '@/lib/dealStage';
import { invoiceView } from '@/lib/invoice';
import { cn } from '@/lib/utils';

/**
 * Сделка — цель deep-link бота (`start_param=deal_<id>`): всё по сделке на одном экране, собрано из
 * списков портала по `deal.id` (отдельного `GET /deals/{id}` в контракте нет); клиенту сделка — её номер
 * и название (`deal.number`, `deal.title`), внутренний id только в адресе. «Написать менеджеру»
 * — бот CRM с контекстом сделки `start=deal_<id>` (M2-CAB-03).
 */
export function DealPage() {
  const { t } = useTranslation();
  const dealId = Number(useParams().id);
  const now = useNow();
  const requests = useRequests();
  const quotes = useQuotes();
  const contracts = useContracts();
  const invoices = useInvoices();
  const acts = useActs();
  const deliveries = useDeliveries();
  const documents = useDocuments({ deal_id: dealId });
  const all = [requests, quotes, contracts, invoices, acts, deliveries, documents];

  // Номер и название сделки берём из любого её объекта: отдельного справочника сделок у клиента нет.
  const of = <T extends { deal?: DealRef | null }>(items: T[] | undefined) => (items ?? []).filter((item) => item.deal?.id === dealId);
  const dealRef = [requests, quotes, contracts, invoices, acts, deliveries, documents]
    .flatMap((query) => of(query.data as Array<{ deal?: DealRef | null }> | undefined))
    .find((item) => item.deal)?.deal;
  const title = dealRef ? t('common.dealNumber', { number: dealRef.number }) : t('pages.deal.titleFallback');
  const subtitle = dealRef?.title ?? null;
  if (all.some((query) => query.isPending)) {
    return (
      <>
        <PageHeader title={title} crumb={dealRef?.number} />
        <ListSkeleton />
      </>
    );
  }
  const failed = all.find((query) => query.isError);
  if (failed) {
    return (
      <>
        <PageHeader title={title} crumb={dealRef?.number} />
        <ErrorState error={failed.error} onRetry={() => all.forEach((query) => void query.refetch())} />
      </>
    );
  }

  const dealRequests = of(requests.data);
  const dealQuotes = of(quotes.data);
  const dealContracts = of(contracts.data);
  const dealInvoices = of(invoices.data);
  const dealActs = of(acts.data);
  const dealLines = of(deliveries.data).sort((a, b) => a.line_no - b.line_no);
  const dealDocuments = documents.data ?? [];
  const empty = [dealRequests, dealQuotes, dealContracts, dealInvoices, dealActs, dealLines, dealDocuments].every((list) => list.length === 0);

  if (empty) {
    return (
      <>
        <PageHeader title={title} crumb={dealRef?.number} />
        <EmptyState icon={Briefcase} title={t('common.notFoundTitle')} text={t('common.notFoundText')}>
          <Button asChild variant="outline">
            <Link to="/requests">{t('pages.deal.toRequests')}</Link>
          </Button>
        </EmptyState>
      </>
    );
  }

  const progress = dealProgress({
    requests: dealRequests,
    quotes: dealQuotes,
    contracts: dealContracts,
    invoices: dealInvoices,
    acts: dealActs,
    deliveries: dealLines,
  });

  return (
    <>
      <PageHeader
        title={title}
        crumb={dealRef?.number}
        subtitle={subtitle}
        icon={Briefcase}
        actions={<ManagerButton dealId={dealId} />}
      />

      <DealStages progress={progress} />

      <div className="flex flex-col gap-6">
        <DealSection title={t('pages.deal.requests')} count={dealRequests.length}>
          {dealRequests.map((item) => (
            <DealRow key={item.id} to={`/requests/${item.id}`} title={item.number} meta={formatDate(item.created_at)}>
              <StatusBadge entity="request" code={item.status} />
            </DealRow>
          ))}
        </DealSection>
        <DealSection title={t('pages.deal.quotes')} count={dealQuotes.length}>
          {dealQuotes.map((item) => (
            <DealRow
              key={item.id}
              to={`/quotes/${item.id}`}
              title={t('pages.quotes.numberVersion', { number: item.number, version: item.version })}
              meta={formatMoney(item.total)}
            >
              <StatusBadge entity="quote" code={item.status} />
            </DealRow>
          ))}
        </DealSection>
        <DealSection title={t('pages.deal.contracts')} count={dealContracts.length}>
          {dealContracts.map((item) => (
            <DealRow key={item.id} to="/contracts" title={item.number}>
              <StatusBadge entity="contract" code={item.status} />
            </DealRow>
          ))}
        </DealSection>
        <DealSection title={t('pages.deal.invoices')} count={dealInvoices.length}>
          {dealInvoices.map((item) => (
            <DealRow key={item.id} to="/invoices" title={item.number} meta={formatMoney(item.total)}>
              <StatusBadge entity="invoice" code={invoiceView(item, now).displayStatus} />
            </DealRow>
          ))}
        </DealSection>
        <DealSection title={t('pages.deal.acts')} count={dealActs.length}>
          {dealActs.map((item) => (
            <DealRow key={item.id} to="/acts" title={item.number} meta={formatDate(item.issued_at)}>
              <StatusBadge entity="act" code={item.status} />
            </DealRow>
          ))}
        </DealSection>
        <DealSection title={t('pages.deal.deliveries')} count={dealLines.length}>
          {dealLines.map((line) => (
            <DealRow key={line.id} to="/deliveries" title={line.title} meta={formatQuantity(line.quantity, line.unit)}>
              <StatusBadge entity="delivery" code={line.status} />
            </DealRow>
          ))}
        </DealSection>
        <DealSection title={t('pages.deal.documents')} count={dealDocuments.length}>
          {dealDocuments.map((doc) => (
            <li key={doc.id} className="portal-card flex min-w-0 flex-wrap items-center justify-between gap-2 p-3 text-sm">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-accent text-primary">
                  <FileText className="size-4" aria-hidden="true" />
                </div>
                <span className="min-w-0 font-medium break-words text-foreground">{doc.title}</span>
              </div>
              <DocumentButton documentId={doc.id} fileName={doc.file_name ?? `${doc.number}.pdf`} label={doc.title} variant="ghost" />
            </li>
          ))}
        </DealSection>
      </div>
    </>
  );
}

function DealSection({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  if (count === 0) return null;
  return (
    <section aria-label={title}>
      <SectionTitle>{title}</SectionTitle>
      <ul className="flex flex-col gap-2">{children}</ul>
    </section>
  );
}

function DealRow({ to, title, meta, children }: { to: string; title: string; meta?: string; children: ReactNode }) {
  return (
    <li>
      <Link
        to={to}
        className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-lg border bg-card p-3 text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="min-w-0 font-medium break-words">{title}</span>
        <span className="flex flex-wrap items-center gap-2">
          {meta ? <span className="text-muted-foreground">{meta}</span> : null}
          {children}
        </span>
      </Link>
    </li>
  );
}

/** Этапы сделки по статусам документов (`lib/dealStage`): выполнено, в работе, впереди; закрытый запрос — без «в работе». */
function DealStages({ progress }: { progress: DealProgress }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="deal-stages" className="mb-6 rounded-2xl border border-border/60 bg-muted/60 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
        <h2 id="deal-stages" className="font-semibold tracking-wider text-primary uppercase">
          {t('pages.deal.stages.title')}
        </h2>
        {progress.closed ? <span className="font-medium text-muted-foreground">{t('pages.deal.stages.closed')}</span> : null}
      </div>
      <ol className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {progress.stages.map((stage, index) => (
          <li
            key={stage.id}
            aria-current={stage.state === 'active' ? 'step' : undefined}
            className={cn(
              'flex items-center gap-2 rounded-xl border p-2.5 text-xs',
              stage.state === 'done'
                ? 'border-success/30 bg-success/10 font-medium text-success'
                : stage.state === 'active'
                  ? 'border-warning/30 bg-warning/10 font-semibold text-warning shadow-2xs'
                  : 'border-border/60 bg-background text-muted-foreground',
            )}
          >
            {stage.state === 'done' ? (
              <Check className="size-3.5 stroke-[3] text-success" aria-hidden="true" />
            ) : (
              <span className="font-mono text-xs" aria-hidden="true">
                {index + 1}.
              </span>
            )}
            <span className="truncate">{t(`pages.deal.stages.${stage.id}`)}</span>
            <span className="sr-only">{`, ${t(`pages.deal.stages.state.${stage.state}`)}`}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
