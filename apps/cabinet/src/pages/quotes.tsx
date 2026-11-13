import { useId, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Clock, FileSignature, FileText, Loader2, Mail, MessageCircle, RotateCw, SearchX, Send, XCircle } from 'lucide-react';
import { toast } from '@/lib/toast';

import { apiErrorKey } from '@/api/errors';
import { isPortalApiError, type AcceptanceCodeSent, type CodeDelivery, type Quote, type QuoteComment, type QuoteLine, type QuoteListItem } from '@/api/portal';
import {
  useAcceptQuote,
  useAddQuoteComment,
  useContracts,
  useQuote,
  useQuoteCodeDelivery,
  useQuotes,
  useRejectQuote,
  useRequestQuoteCode,
} from '@/api/queries';
import { ActionDialog } from '@/components/ActionDialog';
import { ConsequenceCallout } from '@/components/ConsequenceCallout';
import { DealLink, DetailList, SectionTitle, SummaryNote } from '@/components/Details';
import { DocumentButton } from '@/components/DocumentButton';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { DetailSkeleton, ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ReasonDialog } from '@/components/ReasonDialog';
import { ResponsiveList } from '@/components/ResponsiveList';
import { QuoteStatusBadge, ToneBadge } from '@/components/StatusBadge';
import { ManagerButton } from '@/components/TelegramLinkButton';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useMediaQuery, DESKTOP_QUERY } from '@/hooks/useMediaQuery';
import { useNow } from '@/hooks/useNow';
import { formatDate, formatDateTime, formatMoney, formatQuantity } from '@/lib/format';
import { ACCEPT_CODE_MAX, ACCEPT_CODE_MIN, normalizeAcceptCode, quoteAwaitsDecision, quoteExpired } from '@/lib/quotes';
import { cn } from '@/lib/utils';
import { CanAct } from '@/session/CanAct';
import { useMe } from '@/session/useMe';

/**
 * КП (B2B `QuotesPage`, `BuyerAcceptedPanel`, `RejectQuoteDialog`): список всех версий, карточка со
 * строками (позиции, разделы, заметки, этапы), итог, срок действия и обещанные даты по строкам.
 * «Принять» — по коду акцепта, который ERP шлёт по запросу (`request-code` → `POST /quotes/{id}/accept {code}`), «Отклонить» —
 * с обязательной причиной. После акцепта — «что дальше»: договор формируется ERP и появится в «Договорах».
 */
export function QuotesPage() {
  const { t } = useTranslation();
  const quotes = useQuotes();
  const now = useNow();
  const awaiting = (quotes.data ?? []).filter((quote) => quoteAwaitsDecision(quote, now)).length;

  return (
    <>
      <PageHeader title={t('pages.quotes.title')} icon={FileText} />
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
              { id: 'status', header: t('pages.quotes.columns.status'), cell: (row) => <QuoteStatusBadge quote={row} now={now} /> },
              { id: 'total', header: t('pages.quotes.columns.total'), cell: (row) => formatMoney(row.total), className: 'text-right tabular-nums whitespace-nowrap' },
              { id: 'valid', header: t('pages.quotes.columns.validUntil'), cell: (row) => formatDate(row.valid_until) },
              { id: 'sent', header: t('pages.quotes.columns.sent'), cell: (row) => formatDate(row.sent_at) },
              { id: 'deal', header: t('pages.quotes.columns.deal'), cell: (row) => <DealLink deal={row.deal} /> },
            ]}
          />
        </>
      )}
    </>
  );
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
        crumb={quote.number}
        actions={
          <>
            {quote.pdf_document_id ? (
              <DocumentButton documentId={quote.pdf_document_id} fileName={`${quote.number}.pdf`} label={quote.number} />
            ) : null}
            <ManagerButton
              context={{ kind: 'quote', id: quote.id, number: quote.number }}
              label={t('manager.aboutQuote', { number: quote.number })}
            />
          </>
        }
      />
      <div className="flex flex-col gap-4">
        {quote.status === 'accepted' ? <AcceptedPanel dealId={quote.deal.id} /> : null}
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
              <QuoteStatusBadge quote={quote} now={now} />
              <span className="text-sm text-muted-foreground">{t('pages.quoteDetail.version', { version: quote.version })}</span>
            </div>
            <DetailList
              items={[
                { label: t('pages.quoteDetail.total'), value: <span className="text-base">{formatMoney(quote.total)}</span> },
                { label: t('pages.quoteDetail.validUntil'), value: formatDate(quote.valid_until) },
                { label: t('pages.quoteDetail.sent'), value: formatDateTime(quote.sent_at) },
                { label: t('pages.quoteDetail.deal'), value: <DealLink deal={quote.deal} showTitle /> },
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
          <QuoteLines lines={quote.lines} subtotal={quote.subtotal} vat={quote.vat} total={quote.total} />
        </section>

        <QuoteComments quote={quote} awaiting={awaiting} />
      </div>

      <AcceptDialog quote={quote} open={dialog === 'accept'} onOpenChange={(open) => setDialog(open ? 'accept' : null)} />
      <RejectDialog quote={quote} open={dialog === 'reject'} onOpenChange={(open) => setDialog(open ? 'reject' : null)} />
    </>
  );
}

/** Строки КП: разделы — подзаголовки, заметки — пояснения, позиции и этапы — с количеством, ценой и сроком. */
function QuoteLines({
  lines,
  subtotal,
  vat,
  total,
}: {
  lines: QuoteLine[];
  subtotal: Quote['subtotal'];
  vat: Quote['vat'];
  total: Quote['total'];
}) {
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
                  <td className="px-3 py-2 text-right tabular-nums">{formatQuantity(line.quantity, line.unit)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatMoney(line.unit_price)}</td>
                  <td className="px-3 py-2 text-right tabular-nums font-medium">{formatMoney(line.total)}</td>
                  <td className="px-3 py-2">{formatDate(line.promised_date)}</td>
                </tr>
              ),
            )}
          </tbody>
          <tfoot>
            <tr className="border-t">
              <th scope="row" colSpan={3} className="px-3 pt-3 pb-1 text-right font-normal text-muted-foreground">
                {t('pages.quoteDetail.subtotal')}
              </th>
              <td className="px-3 pt-3 pb-1 text-right tabular-nums">{formatMoney(subtotal)}</td>
              <td />
            </tr>
            <tr>
              <th scope="row" colSpan={3} className="px-3 py-1 text-right font-normal text-muted-foreground">
                {t('pages.quoteDetail.vat')}
              </th>
              <td className="px-3 py-1 text-right tabular-nums">{formatMoney(vat)}</td>
              <td />
            </tr>
            <tr>
              <th scope="row" colSpan={3} className="px-3 pt-1 pb-3 text-right font-semibold">
                {t('pages.quoteDetail.grandTotal')}
              </th>
              <td className="px-3 pt-1 pb-3 text-right tabular-nums text-base font-semibold">{formatMoney(total)}</td>
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
                    <dd className="text-right tabular-nums">{formatQuantity(line.quantity, line.unit)}</dd>
                  </>
                ) : null}
                {line.unit_price ? (
                  <>
                    <dt className="text-muted-foreground">{t('pages.quoteDetail.columns.price')}</dt>
                    <dd className="text-right tabular-nums">{formatMoney(line.unit_price)}</dd>
                  </>
                ) : null}
                <dt className="text-muted-foreground">{t('pages.quoteDetail.columns.total')}</dt>
                <dd className="text-right tabular-nums font-medium">{formatMoney(line.total)}</dd>
                {line.promised_date ? (
                  <>
                    <dt className="text-muted-foreground">{t('pages.quoteDetail.columns.date')}</dt>
                    <dd className="text-right tabular-nums">{formatDate(line.promised_date)}</dd>
                  </>
                ) : null}
              </dl>
            </li>
          ),
        )}
      </ul>
      <div role="group" aria-label={t('pages.quoteDetail.totals')}>
        <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 rounded-lg border bg-card p-3 text-sm">
          <dt className="text-muted-foreground">{t('pages.quoteDetail.subtotal')}</dt>
          <dd className="text-right tabular-nums">{formatMoney(subtotal)}</dd>
          <dt className="text-muted-foreground">{t('pages.quoteDetail.vat')}</dt>
          <dd className="text-right tabular-nums">{formatMoney(vat)}</dd>
          <dt className="font-semibold">{t('pages.quoteDetail.grandTotal')}</dt>
          <dd className="text-right tabular-nums text-base font-semibold">{formatMoney(total)}</dd>
        </dl>
      </div>
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
function AcceptedPanel({ dealId }: { dealId: number }) {
  const { t } = useTranslation();
  const contracts = useContracts();
  const contract = (contracts.data ?? []).find((item) => item.deal.id === dealId && item.status !== 'cancelled');
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

type T = ReturnType<typeof useTranslation>['t'];
const KNOWN_REASONS = ['smtp_not_configured', 'rejected', 'unavailable'];

/**
 * Строка о коде (0.10, FR-12): письмо ушло — «Код отправлен»; в очереди — «Отправляем код…», дольше минуты — подсказка;
 * не ушло — причина словами и куда обратиться. Telegram (без журнала доставки) — как раньше.
 */
function codeStatusText(t: T, sent: AcceptanceCodeSent, delivery: CodeDelivery | undefined, waitedTooLong: boolean): string {
  const minutes = Math.max(1, Math.round(sent.expires_in / 60));
  if (sent.channel !== 'email' || delivery?.state === 'sent') return t(codeSentKey(sent), { to: sent.sent_to, minutes });
  if (delivery?.state === 'failed') {
    const reason = delivery.reason && KNOWN_REASONS.includes(delivery.reason) ? delivery.reason : 'other';
    return t('pages.quoteDetail.codeDelivery.notSent', { reason: t(`pages.quoteDetail.codeDelivery.reasons.${reason}`) });
  }
  if (sent.delivery !== null && delivery?.state === 'queued' && waitedTooLong) {
    return t('pages.quoteDetail.codeDelivery.queuedLong');
  }
  return t('pages.quoteDetail.codeDelivery.sending', { to: sent.sent_to });
}

/** Текст про отправленный код: у Telegram адрес бывает просто «Telegram» — не повторяем его дважды. */
function codeSentKey(sent: AcceptanceCodeSent): string {
  if (sent.channel === 'email') return 'pages.quoteDetail.codeSent.email';
  return sent.sent_to === 'Telegram' ? 'pages.quoteDetail.codeSent.telegram' : 'pages.quoteDetail.codeSent.telegramTo';
}

/**
 * Акцепт КП в два шага (контракт 0.2.0, мастер-кода нет): «Получить код» → `POST /quotes/{id}/request-code`,
 * ERP шлёт код контакту в Telegram или на e-mail и отвечает каналом и замаскированным адресом; затем клиент
 * вводит код → `POST /quotes/{id}/accept {code}`. Ошибки остаются в диалоге текстом по `ErrorCode`.
 */
function AcceptDialog({ quote, open, onOpenChange }: { quote: Quote; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation();
  const id = useId();
  const accept = useAcceptQuote(quote.id);
  const requestCode = useRequestQuoteCode(quote.id);
  const [code, setCode] = useState('');
  const [tooShort, setTooShort] = useState(false);
  // Последний полученный ответ хранится отдельно: повторный `mutate` обнуляет `requestCode.data`, а упавший повтор
  // (429 из общего лимита) не должен отнимать у клиента поле для уже пришедшего кода.
  const [sent, setSent] = useState<AcceptanceCodeSent | null>(null);
  // 0.10 (FR-12): итог письма с кодом — от почтового сервиса компании; «отправлен» не пишем заранее.
  const [sentAt, setSentAt] = useState(0);
  const delivery = useQuoteCodeDelivery(quote.id, sent?.delivery ?? null, sentAt);

  const close = (next: boolean) => {
    if (!next) {
      setCode('');
      setTooShort(false);
      accept.reset();
      requestCode.reset();
      setSent(null);
    }
    onOpenChange(next);
  };

  const getCode = () => {
    accept.reset();
    requestCode.mutate(undefined, {
      onSuccess: (result) => {
        setCode('');
        setSent(result);
        setSentAt(Date.now());
      },
    });
  };

  const submit = () => {
    if (!sent) {
      getCode();
      return;
    }
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
      description={t(sent ? 'pages.quoteDetail.acceptText' : 'pages.quoteDetail.requestCodeText', { total: formatMoney(quote.total) })}
      confirmLabel={sent ? t('pages.quoteDetail.acceptConfirm') : t('pages.quoteDetail.requestCode')}
      pending={sent ? accept.isPending : requestCode.isPending}
      error={accept.error ?? requestCode.error}
      message={tooShort ? t('pages.quoteDetail.codeTooShort', { min: ACCEPT_CODE_MIN }) : null}
      onSubmit={submit}
    >
      {sent ? (
        <div className="flex flex-col gap-3">
          <p role="status" className="flex items-start gap-2 rounded-lg border bg-muted px-3 py-2 text-sm">
            {sent.channel === 'telegram' ? (
              <MessageCircle className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            ) : (
              <Mail className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            )}
            <span className="min-w-0 break-words">
              {codeStatusText(t, sent, delivery.data, delivery.dataUpdatedAt - sentAt >= 60_000)}
            </span>
          </p>
          <div className="flex flex-col gap-2">
            <Label htmlFor={id}>{t('pages.quoteDetail.code')}</Label>
            <Input
              id={id}
              value={code}
              autoComplete="one-time-code"
              inputMode="numeric"
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
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="self-start"
            disabled={requestCode.isPending || accept.isPending}
            onClick={getCode}
          >
            <RotateCw aria-hidden="true" />
            {t('pages.quoteDetail.resendCode')}
          </Button>
        </div>
      ) : null}
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

const COMMENT_MAX = 2000;

/**
 * Комментарии к КП (SPEC-v3 §8 «КП — принять / отклонить с причиной / комментарий»): лента `Quote.comments` и поле,
 * пока КП ждёт решения. Комментарий получает менеджер (карточка КП в Платформе и уведомление); КП он не меняет.
 */
function QuoteComments({ quote, awaiting }: { quote: Quote; awaiting: boolean }) {
  const { t } = useTranslation();
  const id = useId();
  const add = useAddQuoteComment(quote.id);
  const [text, setText] = useState('');
  const [missing, setMissing] = useState(false);

  const send = (event: React.FormEvent) => {
    event.preventDefault();
    if (add.isPending) return;
    const value = text.trim();
    if (!value) {
      setMissing(true);
      return;
    }
    add.mutate(value, {
      onSuccess: () => {
        setText('');
        toast.success(t('pages.quoteDetail.commentSent'));
      },
    });
  };
  const problem = missing ? t('pages.quoteDetail.commentRequired') : add.error ? t(apiErrorKey(add.error)) : null;

  return (
    <section aria-labelledby={`${id}-title`}>
      <SectionTitle>
        <span id={`${id}-title`}>{t('pages.quoteDetail.comments')}</span>
      </SectionTitle>
      <Card>
        <CardContent className="flex flex-col gap-4">
          {quote.comments.length ? (
            <ol className="flex flex-col gap-3" aria-label={t('pages.quoteDetail.commentsListLabel', { number: quote.number })}>
              {quote.comments.map((comment) => (
                <CommentItem key={comment.id} comment={comment} />
              ))}
            </ol>
          ) : (
            <p className="text-sm text-muted-foreground">{t('pages.quoteDetail.commentsEmpty')}</p>
          )}
          {awaiting ? (
            <CanAct>
              <form className="flex flex-col gap-3 border-t pt-4" onSubmit={send} noValidate>
                <div className="flex flex-col gap-2">
                  <Label htmlFor={`${id}-text`}>{t('pages.quoteDetail.commentLabel')}</Label>
                  <Textarea
                    id={`${id}-text`}
                    rows={3}
                    maxLength={COMMENT_MAX}
                    value={text}
                    placeholder={t('pages.quoteDetail.commentPlaceholder')}
                    aria-invalid={missing ? true : undefined}
                    aria-describedby={problem ? `${id}-problem` : undefined}
                    onChange={(event) => {
                      setText(event.target.value);
                      setMissing(false);
                      add.reset();
                    }}
                  />
                  {problem ? (
                    <p id={`${id}-problem`} role="alert" className="text-sm text-destructive">
                      {problem}
                    </p>
                  ) : null}
                </div>
                <ConsequenceCallout text={t('pages.quoteDetail.commentConsequence')} />
                <Button type="submit" variant="outline" className="self-start" disabled={add.isPending}>
                  {add.isPending ? <Loader2 className="motion-safe:animate-spin" aria-hidden="true" /> : <Send aria-hidden="true" />}
                  {t('pages.quoteDetail.commentSend')}
                </Button>
              </form>
            </CanAct>
          ) : null}
        </CardContent>
      </Card>
    </section>
  );
}

function CommentItem({ comment }: { comment: QuoteComment }) {
  const { t } = useTranslation();
  const me = useMe();
  const author =
    comment.author === 'manager'
      ? [t('pages.quoteDetail.commentAuthorManager'), comment.author_name].filter(Boolean).join(' · ')
      : comment.author_name && comment.author_name === me.data?.contact.name
        ? t('pages.quoteDetail.commentAuthorYou')
        : (comment.author_name ?? t('pages.quoteDetail.commentAuthorClient'));
  return (
    <li className={cn('flex min-w-0 flex-col gap-1 rounded-lg border p-3 text-sm', comment.author === 'manager' ? 'bg-muted' : 'bg-card')}>
      <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <span className="font-medium">{author}</span>
        <time className="text-xs text-muted-foreground" dateTime={comment.created_at}>
          {formatDateTime(comment.created_at)}
        </time>
      </span>
      <p className="whitespace-pre-line break-words">{comment.text}</p>
    </li>
  );
}
