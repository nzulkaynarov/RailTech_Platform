import { useEffect, useId, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BookOpen, FilePlus2, Inbox, Loader2, Lock, Paperclip, Plus, SearchX, Trash2, Upload } from 'lucide-react';
import { toast } from '@/lib/toast';

import { apiErrorKey } from '@/api/errors';
import type { AttachmentRef, ClientRequest, RequestLineIn } from '@/api/portal';
import { useCatalog, useCreateRequest, useQuotes, useRequest, useRequests, useUploadFile } from '@/api/queries';
import { ActionRequiredWidget } from '@/components/ActionRequiredWidget';
import { DealLink, DetailList, SectionTitle } from '@/components/Details';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ResponsiveList } from '@/components/ResponsiveList';
import { StatusBadge } from '@/components/StatusBadge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { formatDate, formatDateTime, formatFileSize, formatMoney, formatQuantity } from '@/lib/format';
import { normalizeQuantity, requestSourceKey, type NewRequestPrefill } from '@/lib/requests';
import { clearRequestDraft, loadRequestDraft, requestDraftKey, saveRequestDraft } from '@/lib/requestDraft';
import { MAX_UPLOAD_BYTES } from '@/lib/upload';
import { CanAct } from '@/session/CanAct';
import { useMe } from '@/session/useMe';

/**
 * Запросы клиента (B2B `MyRequestsPage` / `RequestDetailPage`, покупательская часть): список, карточка
 * и «Новый запрос» — краткое описание, спецификация строк и загрузка вложений (Q-14..Q-16).
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
      <ActionRequiredWidget />
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
            { id: 'deal', header: t('pages.requests.columns.deal'), cell: (row) => <DealLink deal={row.deal} /> },
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
  const detailQuery = useRequest(id);
  const quotes = useQuotes();
  const request = detailQuery.data ?? requests.data?.find((item) => item.id === id);

  if (requests.isPending && detailQuery.isPending) return <ListSkeleton rows={2} />;
  if (requests.isError && detailQuery.isError) return <ErrorState error={requests.error} onRetry={() => void requests.refetch()} />;
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

  const dealId = request.deal?.id;
  const dealQuotes = dealId === undefined ? [] : (quotes.data ?? []).filter((quote) => quote.deal.id === dealId);

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
            <p className="text-sm whitespace-pre-line wrap-break-word">{request.summary}</p>
            <DetailList
              items={[
                { label: t('pages.requestDetail.created'), value: formatDateTime(request.created_at) },
                request.source ? { label: t('pages.requestDetail.source'), value: t(requestSourceKey(request.source)) } : null,
                { label: t('pages.requestDetail.deal'), value: <DealLink deal={request.deal} showTitle /> },
              ]}
            />
          </CardContent>
        </Card>

        {request.lines && request.lines.length > 0 ? (
          <section aria-labelledby="request-lines">
            <SectionTitle>
              <span id="request-lines">{t('pages.requestDetail.linesTitle')}</span>
            </SectionTitle>
            <div className="rounded-lg border bg-card">
              <ul className="flex flex-col divide-y">
                {request.lines.map((line, idx) => (
                  <li key={idx} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
                    <span className="font-medium wrap-break-word">{line.text}</span>
                    {line.quantity ? (
                      <span className="text-muted-foreground">{formatQuantity(line.quantity, line.unit)}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          </section>
        ) : null}

        {request.attachments && request.attachments.length > 0 ? (
          <section aria-labelledby="request-attachments">
            <SectionTitle>
              <span id="request-attachments">{t('pages.requestDetail.attachmentsTitle')}</span>
            </SectionTitle>
            <div className="rounded-lg border bg-card">
              <ul className="flex flex-col divide-y">
                {request.attachments.map((file) => (
                  <li key={file.upload_id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
                    <span className="flex items-center gap-2">
                      <Paperclip className="size-4 text-muted-foreground" aria-hidden="true" />
                      <span className="font-medium wrap-break-word">{file.name}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </section>
        ) : null}

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

/** Загруженный файл: размер нужен только для показа, в запрос уходит `AttachmentRef` без него (контракт 0.2.0). */
interface UploadedFileRef extends AttachmentRef {
  size_bytes?: number;
}

function RequestForm() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const locationState = useLocation().state as NewRequestPrefill | null;
  const prefillLines = locationState?.lines?.length
    ? locationState.lines
    : locationState?.line
      ? [locationState.line]
      : [];

  const create = useCreateRequest();
  const upload = useUploadFile();
  const summaryId = useId();
  const fileInputId = useId();

  // Черновик (C-9): без предзаполнения из каталога форма поднимается из sessionStorage; предзаполнение — явное
  // действие «Запросить», оно главнее старого черновика и затирает его при первом же сохранении.
  const me = useMe().data;
  const draftKey = me ? requestDraftKey({ companyId: me.company.id, contactId: me.contact.id }) : null;
  const [restored] = useState(() => (prefillLines.length || !draftKey ? null : loadRequestDraft(draftKey)));

  const [summary, setSummary] = useState(() =>
    restored
      ? restored.summary
      : prefillLines.length === 1
        ? t('pages.requestNew.prefillSummary', { name: prefillLines[0].text })
        : prefillLines.length > 1
          ? t('pages.requestNew.prefillSummary', { name: prefillLines.map((l) => l.text).join(', ') })
          : '',
  );
  const [lines, setLines] = useState<LineDraft[]>(() =>
    restored?.lines.length
      ? restored.lines.map((l) => blankLine(l))
      : prefillLines.length
        ? prefillLines.map((l) => blankLine({ text: l.text, unit: l.unit ?? '' }))
        : [blankLine()],
  );
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!draftKey || submitted) return;
    saveRequestDraft(draftKey, { summary, lines: lines.map(({ text, quantity, unit }) => ({ text, quantity, unit })) });
  }, [draftKey, submitted, summary, lines]);

  const [attachments, setAttachments] = useState<UploadedFileRef[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isCatalogPickerOpen, setIsCatalogPickerOpen] = useState(false);
  const [errors, setErrors] = useState<{ summary?: boolean; quantity: number[] }>({ quantity: [] });

  const updateLine = (key: number, patch: Partial<LineDraft>) =>
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));

  const handleFiles = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    setIsUploading(true);
    try {
      for (const file of files) {
        if (file.size > MAX_UPLOAD_BYTES) {
          toast.error(t('apiErrors.FILE_TOO_LARGE'));
          continue;
        }
        const uploaded = await upload.mutateAsync(file);
        setAttachments((current) => [
          ...current,
          {
            upload_id: uploaded.upload_id,
            name: uploaded.name,
            size_bytes: uploaded.size_bytes,
          },
        ]);
      }
    } catch (err) {
      toast.error(t(apiErrorKey(err)));
    } finally {
      setIsUploading(false);
      event.target.value = '';
    }
  };

  const removeAttachment = (uploadId: string) => {
    setAttachments((current) => current.filter((att) => att.upload_id !== uploadId));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const badQuantity = lines.filter((line) => line.quantity.trim() && normalizeQuantity(line.quantity) === null).map((line) => line.key);
    const summaryMissing = !summary.trim();
    setErrors({ summary: summaryMissing, quantity: badQuantity });
    if (summaryMissing || badQuantity.length) return;

    const payloadLines: RequestLineIn[] = lines
      .filter((line) => line.text.trim())
      .map((line) => ({
        text: line.text.trim(),
        quantity: line.quantity.trim() ? normalizeQuantity(line.quantity) : null,
        unit: line.unit.trim() || null,
      }));

    const payload = {
      summary: summary.trim(),
      lines: payloadLines,
      ...(attachments.length > 0
        ? { attachments: attachments.map(({ upload_id, name }): AttachmentRef => ({ upload_id, name })) }
        : {}),
    };

    create.mutate(
      payload,
      {
        onSuccess: (created) => {
          setSubmitted(true);
          if (draftKey) clearRequestDraft(draftKey);
          toast.success(t('pages.requestNew.sent', { number: created.number }));
          navigate(`/requests/${created.id}`, { replace: true });
        },
      },
    );
  };

  return (
    <>
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
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" onClick={() => setLines((current) => [...current, blankLine()])}>
              <Plus aria-hidden="true" />
              {t('pages.requestNew.addLine')}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setIsCatalogPickerOpen(true)}>
              <BookOpen aria-hidden="true" />
              {t('pages.requestNew.pickFromCatalog')}
            </Button>
          </div>
        </fieldset>

        <div className="flex flex-col gap-2">
          <Label htmlFor={fileInputId}>{t('pages.requestNew.attachmentsTitle')}</Label>
          <p className="text-xs text-muted-foreground">{t('pages.requestNew.attachmentsHint')}</p>
          <div className="flex flex-wrap items-center gap-3">
            <input
              id={fileInputId}
              type="file"
              multiple
              className="hidden"
              disabled={isUploading}
              onChange={handleFiles}
            />
            <Button
              type="button"
              variant="outline"
              disabled={isUploading}
              onClick={() => document.getElementById(fileInputId)?.click()}
            >
              {isUploading ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Upload aria-hidden="true" />}
              {isUploading ? t('pages.requestNew.uploading') : t('pages.requestNew.uploadButton')}
            </Button>
          </div>
          {attachments.length > 0 ? (
            <ul className="flex flex-col gap-2 pt-1" aria-label={t('pages.requestNew.attachmentsTitle')}>
              {attachments.map((file) => (
                <li
                  key={file.upload_id}
                  className="flex items-center justify-between gap-2 rounded-lg border bg-card p-2.5 text-sm"
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <Paperclip className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <span className="truncate font-medium">{file.name}</span>
                    {file.size_bytes ? (
                      <span className="shrink-0 text-xs text-muted-foreground">({formatFileSize(file.size_bytes)})</span>
                    ) : null}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="shrink-0"
                    aria-label={t('pages.requestNew.removeFile', { name: file.name })}
                    onClick={() => removeAttachment(file.upload_id)}
                  >
                    <Trash2 aria-hidden="true" />
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        {create.isError ? (
          <Alert variant="destructive">
            <AlertDescription>{t(apiErrorKey(create.error))}</AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button asChild variant="outline">
            <Link
              to="/requests"
              onClick={() => {
                // «Отмена» — осознанный отказ от запроса: черновик не оставляем.
                setSubmitted(true);
                if (draftKey) clearRequestDraft(draftKey);
              }}
            >
              {t('common.cancel')}
            </Link>
          </Button>
          <Button type="submit" disabled={create.isPending || isUploading}>
            {create.isPending ? <Loader2 className="animate-spin" aria-hidden="true" /> : <FilePlus2 aria-hidden="true" />}
            {t('pages.requestNew.submit')}
          </Button>
        </div>
      </form>
      <CatalogPickerDialog
        open={isCatalogPickerOpen}
        onOpenChange={setIsCatalogPickerOpen}
        onSelect={(item) => {
          setLines((current) => [...current, blankLine({ text: item.name, unit: item.unit ?? '' })]);
          toast.success(item.name);
        }}
      />
    </>
  );
}

function CatalogPickerDialog({
  open,
  onOpenChange,
  onSelect,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (item: { name: string; unit?: string | null }) => void;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const catalogQuery = useCatalog({ q: search || undefined, page: 1, page_size: 10 }, open);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85dvh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('pages.requestNew.pickFromCatalog')}</DialogTitle>
          <DialogDescription className="sr-only">{t('pages.requestNew.pickFromCatalog')}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Input
            type="search"
            placeholder={t('pages.catalog.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label={t('pages.catalog.search')}
          />
          {catalogQuery.isPending ? (
            <div className="flex items-center justify-center p-6 text-muted-foreground">
              <Loader2 className="size-6 animate-spin" aria-hidden="true" />
            </div>
          ) : (catalogQuery.data?.items ?? []).length === 0 ? (
            <p className="p-4 text-center text-sm text-muted-foreground">{t('pages.catalog.notFoundTitle')}</p>
          ) : (
            <ul className="flex flex-col divide-y rounded-md border">
              {(catalogQuery.data?.items ?? []).map((item) => (
                <li key={item.id} className="flex items-center justify-between gap-2 p-3 text-sm">
                  <div className="flex flex-col">
                    <span className="font-medium wrap-break-word">{item.name}</span>
                    {item.category ? <span className="text-xs text-muted-foreground">{item.category}</span> : null}
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      onSelect({ name: item.name, unit: item.unit });
                      onOpenChange(false);
                    }}
                  >
                    <Plus aria-hidden="true" />
                    {t('pages.catalog.addToRequest')}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
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
