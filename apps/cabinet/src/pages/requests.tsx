import { useId, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FilePlus2, Inbox, Loader2, Lock, Plus, SearchX, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { apiErrorKey } from '@/api/errors';
import type { ClientRequest, RequestLineIn } from '@/api/portal';
import { useCreateRequest, useQuotes, useRequests } from '@/api/queries';
import { DealLink, DetailList, SectionTitle } from '@/components/Details';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ResponsiveList } from '@/components/ResponsiveList';
import { StatusBadge } from '@/components/StatusBadge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { formatDate, formatDateTime, formatMoney } from '@/lib/format';
import { normalizeQuantity, requestSourceKey, type NewRequestPrefill } from '@/lib/requests';
import { CanAct } from '@/session/CanAct';

/**
 * Запросы клиента (B2B `MyRequestsPage` / `RequestDetailPage`, покупательская часть): список, карточка
 * и «Новый запрос» — краткое описание и строки свободным текстом (BUSINESS §7: позиции с количеством или
 * этапы услуги). Вложений нет, пока в контракте нет загрузки файлов (QUESTIONS Q-14).
 */
function NewRequestButton() {
  const { t } = useTranslation();
  return (
    <CanAct>
      <Button asChild>
        <Link to="/requests/new">
          <Plus aria-hidden="true" />
          {t('pages.requests.new')}
        </Link>
      </Button>
    </CanAct>
  );
}

export function RequestsPage() {
  const { t } = useTranslation();
  const requests = useRequests();

  return (
    <>
      <PageHeader title={t('pages.requests.title')} actions={<NewRequestButton />} />
      {requests.isPending ? (
        <ListSkeleton />
      ) : requests.isError ? (
        <ErrorState error={requests.error} onRetry={() => void requests.refetch()} />
      ) : requests.data.length === 0 ? (
        <EmptyState icon={Inbox} title={t('pages.requests.emptyTitle')} text={t('pages.requests.emptyText')} />
      ) : (
        <ResponsiveList<ClientRequest>
          label={t('pages.requests.title')}
          rows={requests.data}
          getRowId={(row) => row.id}
          rowHref={(row) => `/requests/${row.id}`}
          title={{
            header: t('pages.requests.columns.request'),
            cell: (row) => (
              <span className="flex flex-col gap-0.5">
                <span>{row.number}</span>
                <span className="line-clamp-2 font-normal text-muted-foreground">{row.summary}</span>
              </span>
            ),
          }}
          columns={[
            { id: 'status', header: t('pages.requests.columns.status'), cell: (row) => <StatusBadge entity="request" code={row.status} /> },
            { id: 'created', header: t('pages.requests.columns.created'), cell: (row) => formatDate(row.created_at) },
            { id: 'deal', header: t('pages.requests.columns.deal'), cell: (row) => <DealLink dealId={row.deal_id} /> },
          ]}
        />
      )}
    </>
  );
}

export function RequestDetailPage() {
  const { t } = useTranslation();
  const id = Number(useParams().id);
  const requests = useRequests();
  const quotes = useQuotes();
  const request = requests.data?.find((item) => item.id === id);

  if (requests.isPending) return <ListSkeleton rows={2} />;
  if (requests.isError) return <ErrorState error={requests.error} onRetry={() => void requests.refetch()} />;
  if (!request) {
    return (
      <>
        <PageHeader title={t('common.notFoundTitle')} />
        <EmptyState icon={SearchX} title={t('common.notFoundTitle')} text={t('common.notFoundText')}>
          <Button asChild variant="outline">
            <Link to="/requests">{t('pages.requestDetail.backToList')}</Link>
          </Button>
        </EmptyState>
      </>
    );
  }

  const dealQuotes = request.deal_id === null || request.deal_id === undefined
    ? []
    : (quotes.data ?? []).filter((quote) => quote.deal_id === request.deal_id);

  return (
    <>
      <PageHeader title={t('pages.requestDetail.title', { number: request.number })} />
      <div className="flex flex-col gap-4">
        <Card>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge entity="request" code={request.status} />
              <span className="text-sm text-muted-foreground">{t(`pages.requestDetail.next.${request.status}`)}</span>
            </div>
            <p className="text-sm whitespace-pre-line break-words">{request.summary}</p>
            <DetailList
              items={[
                { label: t('pages.requestDetail.created'), value: formatDateTime(request.created_at) },
                request.source ? { label: t('pages.requestDetail.source'), value: t(requestSourceKey(request.source)) } : null,
                { label: t('pages.requestDetail.deal'), value: <DealLink dealId={request.deal_id} /> },
              ]}
            />
          </CardContent>
        </Card>
        {dealQuotes.length > 0 ? (
          <section aria-labelledby="request-quotes">
            <SectionTitle>
              <span id="request-quotes">{t('pages.requestDetail.quotes')}</span>
            </SectionTitle>
            <ul className="flex flex-col gap-2">
              {dealQuotes.map((quote) => (
                <li key={quote.id}>
                  <Link
                    to={`/quotes/${quote.id}`}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card p-3 text-sm outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="font-medium">
                      {t('pages.quotes.numberVersion', { number: quote.number, version: quote.version })}
                    </span>
                    <span className="flex flex-wrap items-center gap-2">
                      <span>{formatMoney(quote.total)}</span>
                      <StatusBadge entity="quote" code={quote.status} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  );
}

// --- «Новый запрос» ---------------------------------------------------------------------------

interface LineDraft {
  key: number;
  text: string;
  quantity: string;
  unit: string;
}

const SUMMARY_MAX = 5000;
const LINE_MAX = 1000;
let lineKey = 0;
const blankLine = (prefill?: Partial<LineDraft>): LineDraft => ({ key: ++lineKey, text: '', quantity: '', unit: '', ...prefill });

export function RequestNewPage() {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t('pages.requestNew.title')} />
      <CanAct
        fallback={
          <EmptyState icon={Lock} title={t('pages.requestNew.viewOnlyTitle')} text={t('pages.requestNew.viewOnlyText')}>
            <Button asChild variant="outline">
              <Link to="/requests">{t('pages.requestDetail.backToList')}</Link>
            </Button>
          </EmptyState>
        }
      >
        <RequestForm />
      </CanAct>
    </>
  );
}

function RequestForm() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const prefill = (useLocation().state as NewRequestPrefill | null)?.line;
  const create = useCreateRequest();
  const summaryId = useId();
  const [summary, setSummary] = useState(() => (prefill ? t('pages.requestNew.prefillSummary', { name: prefill.text }) : ''));
  const [lines, setLines] = useState<LineDraft[]>(() => [blankLine(prefill ? { text: prefill.text, unit: prefill.unit ?? '' } : undefined)]);
  const [errors, setErrors] = useState<{ summary?: boolean; quantity: number[] }>({ quantity: [] });

  const updateLine = (key: number, patch: Partial<LineDraft>) =>
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const badQuantity = lines.filter((line) => line.quantity.trim() && normalizeQuantity(line.quantity) === null).map((line) => line.key);
    const summaryMissing = !summary.trim();
    setErrors({ summary: summaryMissing, quantity: badQuantity });
    if (summaryMissing || badQuantity.length) return;

    const payload: RequestLineIn[] = lines
      .filter((line) => line.text.trim())
      .map((line) => ({
        text: line.text.trim(),
        quantity: line.quantity.trim() ? normalizeQuantity(line.quantity) : null,
        unit: line.unit.trim() || null,
      }));
    create.mutate(
      { summary: summary.trim(), lines: payload },
      {
        onSuccess: (created) => {
          toast.success(t('pages.requestNew.sent', { number: created.number }));
          navigate(`/requests/${created.id}`, { replace: true });
        },
      },
    );
  };

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Label htmlFor={summaryId}>{t('pages.requestNew.summary')}</Label>
        <p id={`${summaryId}-hint`} className="text-xs text-muted-foreground">
          {t('pages.requestNew.summaryHint')}
        </p>
        <Textarea
          id={summaryId}
          rows={4}
          maxLength={SUMMARY_MAX}
          required
          value={summary}
          aria-describedby={`${summaryId}-hint${errors.summary ? ` ${summaryId}-error` : ''}`}
          aria-invalid={errors.summary || undefined}
          onChange={(event) => setSummary(event.target.value)}
        />
        {errors.summary ? (
          <p id={`${summaryId}-error`} className="text-sm text-destructive">
            {t('pages.requestNew.summaryRequired')}
          </p>
        ) : null}
      </div>

      <fieldset className="flex min-w-0 flex-col gap-3">
        <legend className="mb-1 text-sm font-medium">{t('pages.requestNew.lines')}</legend>
        <p className="text-xs text-muted-foreground">{t('pages.requestNew.linesHint')}</p>
        <ol className="flex flex-col gap-3">
          {lines.map((line, index) => (
            <LineRow
              key={line.key}
              index={index}
              line={line}
              quantityInvalid={errors.quantity.includes(line.key)}
              canRemove={lines.length > 1}
              onChange={(patch) => updateLine(line.key, patch)}
              onRemove={() => setLines((current) => current.filter((item) => item.key !== line.key))}
            />
          ))}
        </ol>
        <Button type="button" variant="outline" className="self-start" onClick={() => setLines((current) => [...current, blankLine()])}>
          <Plus aria-hidden="true" />
          {t('pages.requestNew.addLine')}
        </Button>
      </fieldset>

      <p className="text-xs text-muted-foreground">{t('pages.requestNew.attachmentsLater')}</p>

      {create.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{t(apiErrorKey(create.error))}</AlertDescription>
        </Alert>
      ) : null}

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button asChild variant="outline">
          <Link to="/requests">{t('common.cancel')}</Link>
        </Button>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <FilePlus2 aria-hidden="true" />}
          {t('pages.requestNew.submit')}
        </Button>
      </div>
    </form>
  );
}

function LineRow({
  index,
  line,
  quantityInvalid,
  canRemove,
  onChange,
  onRemove,
}: {
  index: number;
  line: LineDraft;
  quantityInvalid: boolean;
  canRemove: boolean;
  onChange: (patch: Partial<LineDraft>) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const n = index + 1;
  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-lg border bg-card p-3">
      <div className="flex items-end gap-2">
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <Label htmlFor={`${id}-text`}>{t('pages.requestNew.lineText', { n })}</Label>
          <Input
            id={`${id}-text`}
            value={line.text}
            maxLength={LINE_MAX}
            placeholder={t('pages.requestNew.lineTextPlaceholder')}
            onChange={(event) => onChange({ text: event.target.value })}
          />
        </div>
        {canRemove ? (
          <Button type="button" variant="ghost" size="icon" onClick={onRemove} aria-label={t('pages.requestNew.removeLine', { n })}>
            <Trash2 aria-hidden="true" />
          </Button>
        ) : null}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor={`${id}-qty`}>{t('pages.requestNew.quantity')}</Label>
          <Input
            id={`${id}-qty`}
            inputMode="decimal"
            value={line.quantity}
            aria-invalid={quantityInvalid || undefined}
            aria-describedby={quantityInvalid ? `${id}-qty-error` : undefined}
            onChange={(event) => onChange({ quantity: event.target.value })}
          />
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <Label htmlFor={`${id}-unit`}>{t('pages.requestNew.unit')}</Label>
          <Input
            id={`${id}-unit`}
            value={line.unit}
            maxLength={32}
            placeholder={t('pages.requestNew.unitPlaceholder')}
            onChange={(event) => onChange({ unit: event.target.value })}
          />
        </div>
      </div>
      {quantityInvalid ? (
        <p id={`${id}-qty-error`} className="text-sm text-destructive">
          {t('pages.requestNew.quantityInvalid')}
        </p>
      ) : null}
    </li>
  );
}
