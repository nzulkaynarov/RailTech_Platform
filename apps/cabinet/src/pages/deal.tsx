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
import { ConsequenceCallout } from '@/components/ConsequenceCallout';
import { Button } from '@/components/ui/button';
import { useNow } from '@/hooks/useNow';
import { formatDate, formatMoney, formatQuantity } from '@/lib/format';
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
        <PageHeader title={title} />
        <ListSkeleton />
      </>
    );
  }
  const failed = all.find((query) => query.isError);
  if (failed) {
    return (
      <>
        <PageHeader title={title} />
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
        <PageHeader title={title} />
        <EmptyState icon={Briefcase} title={t('common.notFoundTitle')} text={t('common.notFoundText')}>
          <Button asChild variant="outline">
            <Link to="/requests">{t('pages.deal.toRequests')}</Link>
          </Button>
        </EmptyState>
      </>
    );
  }

  // Определение текущего этапа сделки (1..5)
  const currentStep = dealActs.length > 0 ? 5 : dealInvoices.length > 0 ? 4 : dealContracts.length > 0 ? 3 : dealQuotes.length > 0 ? 2 : 1;
  const milestones = [
    { step: 1, title: t('deal.step1', { defaultValue: '1. Запрос' }), active: dealRequests.length > 0 },
    { step: 2, title: t('deal.step2', { defaultValue: '2. КП' }), active: dealQuotes.length > 0 },
    { step: 3, title: t('deal.step3', { defaultValue: '3. Договор' }), active: dealContracts.length > 0 },
    { step: 4, title: t('deal.step4', { defaultValue: '4. Счёт и Оплата' }), active: dealInvoices.length > 0 },
    { step: 5, title: t('deal.step5', { defaultValue: '5. Исполнение и Акт' }), active: dealActs.length > 0 },
  ];

  return (
    <>
      <PageHeader
        title={title}
        subtitle={subtitle}
        icon={Briefcase}
        actions={<ManagerButton dealId={dealId} />}
      />

      {/* Сегментированный прогресс-бар этапов сделки */}
      <div className="mb-6 rounded-2xl border border-hairline bg-alabaster/60 p-4">
        <div className="mb-2 flex items-center justify-between text-xs">
          <span className="font-semibold text-navy uppercase tracking-wider">
            {t('deal.milestones', { defaultValue: 'Этапы жизненного цикла сделки' })}
          </span>
          <span className="font-mono font-semibold tabular-nums text-navy">
            {currentStep}/5
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {milestones.map((m) => {
            const isDone = m.step < currentStep || (m.step === 5 && dealActs.some((a) => a.status === 'accepted'));
            const isCurrent = m.step === currentStep;
            return (
              <div
                key={m.step}
                className={cn(
                  'flex items-center gap-2 rounded-xl border p-2.5 text-xs transition-colors',
                  isDone
                    ? 'border-transparent bg-sage-bg text-sage font-medium'
                    : isCurrent
                      ? 'border-sand-border bg-sand-bg text-sand font-semibold shadow-2xs'
                      : 'border-hairline bg-canvas text-muted-foreground',
                )}
              >
                {isDone ? (
                  <Check className="size-3.5 text-sage stroke-[3]" />
                ) : (
                  <span className="font-mono text-xs">{m.step}.</span>
                )}
                <span className="truncate">{m.title.replace(/^\d+\.\s*/, '')}</span>
              </div>
            );
          })}
        </div>
      </div>

      <ConsequenceCallout className="mb-6" />

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
                <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-coral-bg text-coral">
                  <FileText className="size-4 text-coral" />
                </div>
                <span className="min-w-0 font-medium break-words text-charcoal">{doc.title}</span>
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
