import { useId, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Clock, FileSignature, FileText, SearchX, XCircle } from 'lucide-react';
import { toast } from 'sonner';

import { isPortalApiError, type Quote, type QuoteLine, type QuoteListItem } from '@/api/portal';
import { useAcceptQuote, useContracts, useQuote, useQuotes, useRejectQuote } from '@/api/queries';
import { ActionDialog } from '@/components/ActionDialog';
import { DealLink, DetailList, SectionTitle, SummaryNote } from '@/components/Details';
import { DocumentButton } from '@/components/DocumentButton';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { DetailSkeleton, ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ReasonDialog } from '@/components/ReasonDialog';
import { ResponsiveList } from '@/components/ResponsiveList';
import { StatusBadge, ToneBadge } from '@/components/StatusBadge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useMediaQuery, DESKTOP_QUERY } from '@/hooks/useMediaQuery';
import { useNow } from '@/hooks/useNow';
import { formatDate, formatDateTime, formatMoney, formatQuantity } from '@/lib/format';
import { ACCEPT_CODE_MAX, ACCEPT_CODE_MIN, normalizeAcceptCode, quoteAwaitsDecision, quoteExpired } from '@/lib/quotes';
import { cn } from '@/lib/utils';
import { CanAct } from '@/session/CanAct';

/**
 * КП (B2B `QuotesPage`, `BuyerAcceptedPanel`, `RejectQuoteDialog`): список всех версий, карточка со
 * строками (позиции, разделы, заметки, этапы), итог, срок действия и обещанные даты по строкам.
 * «Принять» — по коду акцепта из сообщения бота/письма (`POST /quotes/{id}/accept {code}`), «Отклонить» —
 * с обязательной причиной. После акцепта — «что дальше»: договор формируется ERP и появится в «Договорах».
 */
export function QuotesPage() {
  const { t } = useTranslation();
  const quotes = useQuotes();
  const now = useNow();
  const awaiting = (quotes.data ?? []).filter((quote) => quoteAwaitsDecision(quote, now)).length;

  return (
    <>
      <PageHeader title={t('pages.quotes.title')} />
      {quotes.isPending ? (
        <ListSkeleton />
      ) : quotes.isError ? (
        <ErrorState error={quotes.error} onRetry={() => void quotes.refetch()} />
      ) : quotes.data.length === 0 ? (
        <EmptyState icon={FileText} title={t('pages.quotes.emptyTitle')} text={t('pages.quotes.emptyText')} />
      ) : (
        <>
          {awaiting > 0 ? <SummaryNote icon={Clock}>{t('pages.quotes.awaiting', { count: awaiting })}</SummaryNote> : null}
          <ResponsiveList<QuoteListItem>
            label={t('pages.quotes.title')}
            rows={quotes.data}
            getRowId={(row) => row.id}
            rowHref={(row) => `/quotes/${row.id}`}
            title={{
              header: t('pages.quotes.columns.quote'),
              cell: (row) => t('pages.quotes.numberVersion', { number: row.number, version: row.version }),
            }}
            columns={[
              { id: 'status', header: t('pages.quotes.columns.status'), cell: (row) => <QuoteStatus quote={row} now={now} /> },
              { id: 'total', header: t('pages.quotes.columns.total'), cell: (row) => formatMoney(row.total), className: 'text-right' },
              { id: 'valid', header: t('pages.quotes.columns.validUntil'), cell: (row) => formatDate(row.valid_until) },
              { id: 'sent', header: t('pages.quotes.columns.sent'), cell: (row) => formatDate(row.sent_at) },
              { id: 'deal', header: t('pages.quotes.columns.deal'), cell: (row) => <DealLink dealId={row.deal_id} /> },
            ]}
          />
        </>
      )}
    </>
  );
}

/** Статус КП; «ждёт решения» с прошедшим сроком показываем как «срок истёк». */
function QuoteStatus({ quote, now }: { quote: Pick<QuoteListItem, 'status' | 'valid_until'>; now: number }) {
  return quoteExpired(quote, now) ? <StatusBadge entity="quote" code="expired" /> : <StatusBadge entity="quote" code={quote.status} />;
}

export function QuoteDetailPage() {
  const { t } = useTranslation();
  const id = Number(useParams().id);
  const quote = useQuote(id);

  if (quote.isPending) return <DetailSkeleton />;
  if (quote.isError) {
    if (isPortalApiError(quote.error, 404)) {
      return (
        <>
          <PageHeader title={t('common.notFoundTitle')} />
          <EmptyState icon={SearchX} title={t('common.notFoundTitle')} text={t('common.notFoundText')}>
            <Button asChild variant="outline">
              <Link to="/quotes">{t('pages.quoteDetail.backToList')}</Link>
            </Button>
          </EmptyState>
        </>
      );
    }
    return <ErrorState error={quote.error} onRetry={() => void quote.refetch()} />;
  }
  return <QuoteCard quote={quote.data} />;
}

function QuoteCard({ quote }: { quote: Quote }) {
  const { t } = useTranslation();
  const now = useNow();
  const expired = quoteExpired(quote, now);
  const awaiting = quoteAwaitsDecision(quote, now);
  const [dialog, setDialog] = useState<'accept' | 'reject' | null>(null);

  return (
    <>
      <PageHeader
        title={t('pages.quoteDetail.title', { number: quote.number })}
        actions={
          quote.pdf_document_id ? (
            <DocumentButton documentId={quote.pdf_document_id} fileName={`${quote.number}.pdf`} label={quote.number} />
          ) : null
        }
      />
      <div className="flex flex-col gap-4">
        {quote.status === 'accepted' ? <AcceptedPanel dealId={quote.deal_id} /> : null}
        {quote.status === 'rejected' ? (
          <Alert>
            <XCircle aria-hidden="true" />
            <AlertTitle>{t('pages.quoteDetail.rejectedTitle')}</AlertTitle>
            {quote.rejected_reason ? (
              <AlertDescription>{t('pages.quoteDetail.rejectedReason', { reason: quote.rejected_reason })}</AlertDescription>
            ) : null}
          </Alert>
        ) : null}
        {expired ? (
          <Alert>
            <Clock aria-hidden="true" />
            <AlertTitle>{t('pages.quoteDetail.expiredTitle')}</AlertTitle>
            <AlertDescription>{t('pages.quoteDetail.expiredText')}</AlertDescription>
          </Alert>
        ) : null}

        <Card>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <QuoteStatus quote={quote} now={now} />
              <span className="text-sm text-muted-foreground">{t('pages.quoteDetail.version', { version: quote.version })}</span>
            </div>
            <DetailList
              items={[
                { label: t('pages.quoteDetail.total'), value: <span className="text-base">{formatMoney(quote.total)}</span> },
                { label: t('pages.quoteDetail.validUntil'), value: formatDate(quote.valid_until) },
                { label: t('pages.quoteDetail.sent'), value: formatDateTime(quote.sent_at) },
                { label: t('pages.quoteDetail.deal'), value: <DealLink dealId={quote.deal_id} /> },
              ]}
            />
            {awaiting ? (
              <CanAct>
                <div className="flex flex-col gap-2 border-t pt-4 sm:flex-row">
                  <Button onClick={() => setDialog('accept')}>
                    <CheckCircle2 aria-hidden="true" />
                    {t('pages.quoteDetail.accept')}
                  </Button>
                  <Button variant="outline" onClick={() => setDialog('reject')}>
                    <XCircle aria-hidden="true" />
                    {t('pages.quoteDetail.reject')}
                  </Button>
                </div>
              </CanAct>
            ) : null}
          </CardContent>
        </Card>

        <section aria-labelledby="quote-lines">
          <SectionTitle>
            <span id="quote-lines">{t('pages.quoteDetail.lines')}</span>
          </SectionTitle>
          <QuoteLines lines={quote.lines} total={quote.total} />
        </section>
      </div>

      <AcceptDialog quote={quote} open={dialog === 'accept'} onOpenChange={(open) => setDialog(open ? 'accept' : null)} />
      <RejectDialog quote={quote} open={dialog === 'reject'} onOpenChange={(open) => setDialog(open ? 'reject' : null)} />
    </>
  );
}

/** Строки КП: разделы — подзаголовки, заметки — пояснения, позиции и этапы — с количеством, ценой и сроком. */
function QuoteLines({ lines, total }: { lines: QuoteLine[]; total: Quote['total'] }) {
  const { t } = useTranslation();
  const desktop = useMediaQuery(DESKTOP_QUERY);
  const sorted = [...lines].sort((a, b) => a.line_no - b.line_no);

  if (desktop) {
    return (
      <div className="rounded-lg border bg-card">
        <table className="w-full text-sm" aria-label={t('pages.quoteDetail.lines')}>
          <thead className="border-b text-left text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">{t('pages.quoteDetail.columns.title')}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">{t('pages.quoteDetail.columns.quantity')}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">{t('pages.quoteDetail.columns.price')}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">{t('pages.quoteDetail.columns.total')}</th>
              <th scope="col" className="px-3 py-2 font-medium">{t('pages.quoteDetail.columns.date')}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((line) =>
              line.kind === 'section' ? (
                <tr key={line.line_no} className="border-b bg-muted">
                  <th scope="rowgroup" colSpan={5} className="px-3 py-2 text-left font-semibold">
                    {line.title}
                  </th>
                </tr>
              ) : line.kind === 'note' ? (
                <tr key={line.line_no} className="border-b">
                  <td colSpan={5} className="px-3 py-2 text-muted-foreground italic">
                    {line.title}
                  </td>
                </tr>
              ) : (
                <tr key={line.line_no} className="border-b align-top">
                  <td className="px-3 py-2">
                    <LineTitle line={line} />
                  </td>
                  <td className="px-3 py-2 text-right">{formatQuantity(line.quantity, line.unit)}</td>
                  <td className="px-3 py-2 text-right">{formatMoney(line.unit_price)}</td>
                  <td className="px-3 py-2 text-right font-medium">{formatMoney(line.total)}</td>
                  <td className="px-3 py-2">{formatDate(line.promised_date)}</td>
                </tr>
              ),
            )}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={3} className="px-3 py-3 text-right font-semibold">
                {t('pages.quoteDetail.grandTotal')}
              </th>
              <td className="px-3 py-3 text-right text-base font-semibold">{formatMoney(total)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col gap-2" aria-label={t('pages.quoteDetail.lines')}>
        {sorted.map((line) =>
          line.kind === 'section' ? (
            <li key={line.line_no} className="pt-2 text-sm font-semibold">
              {line.title}
            </li>
          ) : line.kind === 'note' ? (
            <li key={line.line_no} className="rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
              {line.title}
            </li>
          ) : (
            <li key={line.line_no} className="flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-3 text-sm">
              <LineTitle line={line} />
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
                {line.quantity ? (
                  <>
                    <dt className="text-muted-foreground">{t('pages.quoteDetail.columns.quantity')}</dt>
                    <dd className="text-right">{formatQuantity(line.quantity, line.unit)}</dd>
                  </>
                ) : null}
                {line.unit_price ? (
                  <>
                    <dt className="text-muted-foreground">{t('pages.quoteDetail.columns.price')}</dt>
                    <dd className="text-right">{formatMoney(line.unit_price)}</dd>
                  </>
                ) : null}
                <dt className="text-muted-foreground">{t('pages.quoteDetail.columns.total')}</dt>
                <dd className="text-right font-medium">{formatMoney(line.total)}</dd>
                {line.promised_date ? (
                  <>
                    <dt className="text-muted-foreground">{t('pages.quoteDetail.columns.date')}</dt>
                    <dd className="text-right">{formatDate(line.promised_date)}</dd>
                  </>
                ) : null}
              </dl>
            </li>
          ),
        )}
      </ul>
      <p className="flex items-baseline justify-between gap-3 rounded-lg border bg-card p-3 text-sm font-semibold">
        <span>{t('pages.quoteDetail.grandTotal')}</span>
        <span className="text-base">{formatMoney(total)}</span>
      </p>
    </div>
  );
}

function LineTitle({ line }: { line: QuoteLine }) {
  const { t } = useTranslation();
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="flex flex-wrap items-center gap-2 font-medium break-words">
        {line.title}
        {line.kind === 'stage' ? <ToneBadge tone="neutral">{t('pages.quoteDetail.stage')}</ToneBadge> : null}
      </span>
      {line.description ? <span className="text-muted-foreground break-words">{line.description}</span> : null}
    </span>
  );
}

/** После акцепта (B2B `BuyerAcceptedPanel`): договор ERP создаёт сам — ведём к нему, номер берём из API. */
function AcceptedPanel({ dealId }: { dealId: number | undefined }) {
  const { t } = useTranslation();
  const contracts = useContracts();
  const contract = (contracts.data ?? []).find((item) => item.deal_id === dealId && item.status !== 'cancelled');
  const text = contract
    ? contract.status === 'sent' || contract.status === 'signed_by_company'
      ? t('pages.quoteDetail.acceptedReadyToSign', { number: contract.number })
      : t('pages.quoteDetail.acceptedContract', { number: contract.number })
    : t('pages.quoteDetail.acceptedPending');
  return (
    <Card className="border-success/30 bg-success/5">
      <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-hidden="true" />
          <div className="flex flex-col gap-1" role="status">
            <p className="text-sm font-semibold">{t('pages.quoteDetail.acceptedTitle')}</p>
            <p className="text-sm text-muted-foreground">{text}</p>
          </div>
        </div>
        <Button asChild className="shrink-0">
          <Link to="/contracts">
            <FileSignature aria-hidden="true" />
            {t('pages.quoteDetail.toContracts')}
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function AcceptDialog({ quote, open, onOpenChange }: { quote: Quote; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation();
  const id = useId();
  const accept = useAcceptQuote(quote.id);
  const [code, setCode] = useState('');
  const [tooShort, setTooShort] = useState(false);

  const close = (next: boolean) => {
    if (!next) {
      setCode('');
      setTooShort(false);
      accept.reset();
    }
    onOpenChange(next);
  };

  const submit = () => {
    const value = normalizeAcceptCode(code);
    if (value.length < ACCEPT_CODE_MIN) {
      setTooShort(true);
      return;
    }
    accept.mutate(value, {
      onSuccess: () => {
        toast.success(t('pages.quoteDetail.acceptedToast', { number: quote.number }));
        close(false);
      },
    });
  };

  return (
    <ActionDialog
      open={open}
      onOpenChange={close}
      title={t('pages.quoteDetail.acceptTitle', { number: quote.number })}
      description={t('pages.quoteDetail.acceptText', { total: formatMoney(quote.total) })}
      confirmLabel={t('pages.quoteDetail.acceptConfirm')}
      pending={accept.isPending}
      error={accept.error}
      message={tooShort ? t('pages.quoteDetail.codeTooShort', { min: ACCEPT_CODE_MIN }) : null}
      onSubmit={submit}
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor={id}>{t('pages.quoteDetail.code')}</Label>
        <Input
          id={id}
          value={code}
          autoComplete="one-time-code"
          inputMode="text"
          maxLength={ACCEPT_CODE_MAX + 4}
          aria-describedby={`${id}-hint`}
          aria-invalid={tooShort || isPortalApiError(accept.error, 409) || undefined}
          className={cn('font-mono tracking-widest')}
          onChange={(event) => {
            setCode(event.target.value);
            setTooShort(false);
          }}
        />
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {t('pages.quoteDetail.codeHint')}
        </p>
      </div>
    </ActionDialog>
  );
}

function RejectDialog({ quote, open, onOpenChange }: { quote: Quote; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation();
  const reject = useRejectQuote(quote.id);
  return (
    <ReasonDialog
      target={quote.id}
      open={open}
      onOpenChange={(next) => {
        if (!next) reject.reset();
        onOpenChange(next);
      }}
      title={t('pages.quoteDetail.rejectTitle', { number: quote.number })}
      description={t('pages.quoteDetail.rejectText')}
      label={t('pages.quoteDetail.rejectReason')}
      placeholder={t('pages.quoteDetail.rejectPlaceholder')}
      confirmLabel={t('pages.quoteDetail.rejectConfirm')}
      pending={reject.isPending}
      error={reject.error}
      onConfirm={(reason) =>
        reject.mutate(reason, {
          onSuccess: () => {
            toast.success(t('pages.quoteDetail.rejectedToast', { number: quote.number }));
            onOpenChange(false);
          },
        })
      }
    />
  );
}
