import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Download, PackageOpen, Search, SearchX, Upload, X } from 'lucide-react';

import { apiErrorKey, rowErrorKey } from '@/api/errors';
import {
  listPartnerProducts,
  type PartnerConfirmResult,
  type PartnerProduct,
  type PartnerSubmitResult,
} from '@/api/portal';
import { usePartnerProducts, useConfirmPartnerOffers, useSubmitPartnerProducts } from '@/api/queries';
import { ActionDialog } from '@/components/ActionDialog';
import { ConsequenceCallout } from '@/components/ConsequenceCallout';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { EmptySteps } from '@/components/partner/EmptySteps';
import { OfferCell } from '@/components/partner/OfferCell';
import { PriceListWizard } from '@/components/partner/PriceListWizard';
import { ProductSheet } from '@/components/partner/ProductSheet';
import { ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ResponsiveList } from '@/components/ResponsiveList';
import { StatusBadge } from '@/components/StatusBadge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useUrlParams } from '@/hooks/useUrlParams';
import { pageCount, parsePage } from '@/lib/catalog';
import { downloadTemplate } from '@/lib/priceList';
import { toast } from '@/lib/toast';
import {
  PARTNER_BATCH,
  PARTNER_PAGE_SIZE,
  PARTNER_TABS,
  chunk,
  fieldLabelKey,
  parseTab,
  selectable,
  splitSelection,
  tabStatus,
} from '@/lib/partnerProducts';
import { CanAct } from '@/session/CanAct';

type Notice =
  | { kind: 'submitted'; result: PartnerSubmitResult }
  | { kind: 'confirmed'; result: PartnerConfirmResult };

/** Что подтверждает диалог отправки: номера карточек. */
interface Pending {
  ids: number[];
}

/** id всех карточек вкладки (до `PARTNER_BATCH`): «отправить все черновики» не ограничено страницей списка. */
async function collectIds(status: 'draft'): Promise<number[]> {
  const ids: number[] = [];
  for (let page = 1; ids.length < PARTNER_BATCH; page += 1) {
    const result = await listPartnerProducts({ status, page, page_size: 100 });
    ids.push(...result.items.map((item) => item.id));
    if (page * 100 >= result.total) break;
  }
  return ids.slice(0, PARTNER_BATCH);
}

/**
 * «Мои товары» (модуль `my_products`, PART-2): свои карточки и свои цены. Вкладки по статусам с количеством, поиск и
 * страницы — в адресе (`?tab=&q=&page=`), карточка — `?card=`. Статус карточки, свежесть цены, полноту и «есть изменение на
 * проверке» считает ERP; экран показывает их и ведёт партнёра: загрузить прайс по шаблону → отправить на проверку →
 * подтверждать цены. Публикует сотрудник, из кабинета публикации нет.
 */
export function MyProductsPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const tab = parseTab(params.get('tab'));
  const q = params.get('q') ?? '';
  const page = parsePage(params.get('page'));
  const cardParam = Number(params.get('card'));
  const cardId = Number.isInteger(cardParam) && cardParam > 0 ? cardParam : null;
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [wizard, setWizard] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [collecting, setCollecting] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const submit = useSubmitPartnerProducts();
  const confirm = useConfirmPartnerOffers();

  const query = usePartnerProducts({ status: tabStatus(tab), q: q || undefined, page, page_size: PARTNER_PAGE_SIZE });
  const data = query.data;

  const patchUrl = useUrlParams();
  const update = (patch: Record<string, string | null>) => {
    setSelected(new Set());
    patchUrl(patch);
  };

  const items = data?.items ?? [];
  const { submit: submitIds, confirm: confirmIds } = splitSelection(items, selected);
  const total = data?.total ?? 0;
  const pages = pageCount(total, PARTNER_PAGE_SIZE);
  const openCard = (id: number | null) => patchUrl({ card: id ? String(id) : null });

  const askSubmit = (ids: number[]) => {
    submit.reset();
    setPending({ ids });
  };
  const askSubmitAllDrafts = async () => {
    setCollecting(true);
    try {
      askSubmit(await collectIds('draft'));
    } catch {
      toast.error(t('apiErrors.UNKNOWN'));
    } finally {
      setCollecting(false);
    }
  };
  const runSubmit = () => {
    if (!pending) return;
    // Больше 500 карточек ERP принимает несколькими запросами; итог складываем в одно сообщение
    void (async () => {
      const merged: PartnerSubmitResult = { submitted: [], errors: [] };
      try {
        for (const part of chunk(pending.ids, PARTNER_BATCH)) {
          const result = await submit.mutateAsync(part);
          merged.submitted.push(...result.submitted);
          merged.errors.push(...result.errors);
        }
        setNotice({ kind: 'submitted', result: merged });
        setPending(null);
        setSelected(new Set());
      } catch {
        // ошибка показана в диалоге (submit.error)
      }
    })();
  };
  const runConfirm = (body: { ids: number[] } | { all: true }) => {
    confirm.mutate(body, {
      onSuccess: (result) => {
        setNotice({ kind: 'confirmed', result });
        setSelected(new Set());
      },
      onError: (error) => toast.error(t(apiErrorKey(error))),
    });
  };

  const toggle = (id: number) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const selectableIds = items.filter(selectable).map((item) => item.id);
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  const attention = data?.attention;
  const attentionTotal = attention ? attention.stale + attention.expired + attention.expiring : 0;
  const nothingAtAll = data !== undefined && data.counts.all === 0 && !q;

  return (
    <>
      <PageHeader
        title={t('partner.title')}
        icon={PackageOpen}
        actions={
          <>
            <Button type="button" variant="outline" onClick={() => void downloadTemplate((message) => toast.error(message), t('partner.templateFailed'))}>
              <Download aria-hidden="true" />
              {t('partner.downloadTemplate')}
            </Button>
            <CanAct>
              <Button type="button" onClick={() => setWizard(true)}>
                <Upload aria-hidden="true" />
                {t('partner.uploadPrice')}
              </Button>
            </CanAct>
          </>
        }
      />

      {notice ? <NoticeBanner notice={notice} names={new Map(items.map((item) => [item.id, item.name]))} onClose={() => setNotice(null)} /> : null}

      {query.isPending ? (
        <ListSkeleton rows={4} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : nothingAtAll ? (
        <EmptySteps onTemplate={() => void downloadTemplate((message) => toast.error(message), t('partner.templateFailed'))} onUpload={() => setWizard(true)} />
      ) : (
        <>
          {attention && attentionTotal > 0 ? (
            <Alert className="mb-4 border-warning/40 bg-warning/10">
              <AlertTriangle aria-hidden="true" className="text-warning" />
              <AlertTitle>{t('partner.attention.title')}</AlertTitle>
              <AlertDescription>
                <p>{t('partner.attention.text', attention)}</p>
                {attention.expired > 0 ? <p>{t('partner.attention.expiredHint')}</p> : null}
              </AlertDescription>
            </Alert>
          ) : null}

          <div role="group" aria-label={t('partner.tabsLabel')} className="mb-4 flex flex-wrap gap-2">
            {PARTNER_TABS.filter((name) => name !== 'matched' || name === tab || (data?.counts.matched ?? 0) > 0).map((name) => (
              <Button
                key={name}
                type="button"
                size="sm"
                variant={name === tab ? 'default' : 'outline'}
                aria-pressed={name === tab}
                className="rounded-full"
                onClick={() => update({ tab: name === 'all' ? null : name, page: null })}
              >
                {t(`partner.tabs.${name}`)}
                <span className="ml-1 tabular-nums opacity-80">{data?.counts[name] ?? 0}</span>
              </Button>
            ))}
          </div>

          <SearchForm key={q} initial={q} onSearch={(value) => update({ q: value || null, page: null })} />

          <Toolbar
            selectedCount={selected.size}
            canSubmitSelected={submitIds.length > 0}
            canConfirmSelected={confirmIds.length > 0}
            draftCount={data?.counts.draft ?? 0}
            collecting={collecting}
            confirming={confirm.isPending}
            onSubmitSelected={() => askSubmit(submitIds)}
            onSubmitAll={() => void askSubmitAllDrafts()}
            onConfirmSelected={() => runConfirm({ ids: confirmIds })}
            onConfirmAll={() => runConfirm({ all: true })}
            onClear={() => setSelected(new Set())}
            allSelected={allSelected}
            onToggleAll={() => setSelected(allSelected ? new Set() : new Set(selectableIds))}
            hasSelectable={selectableIds.length > 0}
          />

          {items.length === 0 ? (
            q ? (
              <EmptyState icon={SearchX} title={t('partner.notFoundTitle')} text={t('partner.notFoundText')}>
                <Button variant="outline" onClick={() => update({ q: null, page: null })}>
                  {t('partner.reset')}
                </Button>
              </EmptyState>
            ) : (
              <EmptyState icon={PackageOpen} title={t('partner.tabs.' + tab)} text={t('partner.emptyTab')} />
            )
          ) : (
            <>
              <p className="mb-3 text-sm text-muted-foreground" role="status" aria-live="polite">
                {t('partner.found', { count: total })}
              </p>
              <ResponsiveList
                label={t('partner.list')}
                rows={items}
                getRowId={(item) => item.id}
                rowClassName={(item) => (item.status === 'returned' ? 'bg-warning/5' : undefined)}
                title={{
                  header: t('partner.columns.product'),
                  className: 'min-w-56',
                  cell: (item) => <ProductTitle item={item} checked={selected.has(item.id)} onToggle={() => toggle(item.id)} onOpen={() => openCard(item.id)} />,
                }}
                columns={[
                  { id: 'category', header: t('partner.columns.category'), cell: (item) => item.category ?? '—', className: 'w-36 whitespace-normal' },
                  { id: 'status', header: t('partner.columns.status'), cell: (item) => <StatusCell item={item} />, className: 'w-56 whitespace-normal' },
                  { id: 'price', header: t('partner.columns.price'), cell: (item) => <OfferCell offer={item.offer} />, className: 'w-48 whitespace-normal' },
                  { id: 'completeness', header: t('partner.columns.completeness'), cell: (item) => (item.status === 'matched' ? '—' : t('partner.completenessValue', { percent: item.completeness })), className: 'w-20 text-right' },
                ]}
              />
              {pages > 1 ? (
                <nav aria-label={t('partner.pagination')} className="mt-4 flex items-center justify-between gap-2">
                  <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => update({ page: page - 1 > 1 ? String(page - 1) : null })}>
                    <ChevronLeft aria-hidden="true" />
                    {t('partner.prev')}
                  </Button>
                  <span className="text-sm text-muted-foreground">{t('partner.page', { page, pages })}</span>
                  <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>
                    {t('partner.next')}
                    <ChevronRight aria-hidden="true" />
                  </Button>
                </nav>
              ) : null}
            </>
          )}
        </>
      )}

      <ProductSheet id={cardId} onClose={() => openCard(null)} />
      <PriceListWizard
        open={wizard}
        onOpenChange={setWizard}
        onGoDrafts={() => {
          setWizard(false);
          update({ tab: 'draft', page: null, q: null });
        }}
      />
      <ActionDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title={t('partner.submitDialog.title')}
        description={pending ? t('partner.submitDialog.description', { count: pending.ids.length }) : ''}
        confirmLabel={t('partner.submitDialog.confirm')}
        pending={submit.isPending}
        error={submit.error}
        message={pending && pending.ids.length === 0 ? t('partner.submitDialog.nothing') : null}
        onSubmit={runSubmit}
      >
        <ConsequenceCallout text={t('partner.submitDialog.consequence')} />
      </ActionDialog>
    </>
  );
}

function ProductTitle({ item, checked, onToggle, onOpen }: { item: PartnerProduct; checked: boolean; onToggle: () => void; onOpen: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-w-0 items-start gap-3">
      {/* Выбирать карточки — только контакту с правом действовать (отправка и подтверждение — его действия) */}
      <CanAct>
        {selectable(item) ? (
          <Checkbox checked={checked} onCheckedChange={onToggle} aria-label={t('partner.selectRow', { name: item.name })} className="mt-1" />
        ) : (
          <span className="w-4 shrink-0" aria-hidden="true" />
        )}
      </CanAct>
      <div className="min-w-0">
        <button
          type="button"
          onClick={onOpen}
          aria-label={t('partner.openCard', { name: item.name })}
          className="rounded-sm text-left font-medium underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
        >
          {item.name}
        </button>
        <p className="text-xs text-muted-foreground">{[item.brand, item.manufacturer_part_number].filter(Boolean).join(' · ') || '—'}</p>
      </div>
    </div>
  );
}

function StatusCell({ item }: { item: PartnerProduct }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-w-0 flex-col items-start gap-1 text-left">
      <StatusBadge entity="partner" code={item.status} />
      {item.has_pending_change ? <span className="text-xs text-info">{t('partner.pendingChange')}</span> : null}
      {item.status === 'returned' ? (
        <div className="text-xs break-words text-warning">
          {item.return_reason ? <p>{t('partner.returnedReason', { reason: item.return_reason })}</p> : null}
          {item.return_issues.length > 0 ? (
            <p>{item.return_issues.map((issue) => t(fieldLabelKey(issue.field))).join(', ')}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function SearchForm({ initial, onSearch }: { initial: string; onSearch: (value: string) => void }) {
  const { t } = useTranslation();
  const [value, setValue] = useState(initial);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSearch(value.trim());
  };
  return (
    <form role="search" onSubmit={submit} className="mb-4 flex gap-2">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <Label htmlFor="partner-search" className="sr-only">
          {t('partner.searchLabel')}
        </Label>
        <Input id="partner-search" type="search" value={value} placeholder={t('partner.search')} onChange={(event) => setValue(event.target.value)} />
      </div>
      <Button type="submit" variant="outline">
        <Search aria-hidden="true" />
        {t('partner.searchLabel')}
      </Button>
    </form>
  );
}

function Toolbar(props: {
  selectedCount: number;
  canSubmitSelected: boolean;
  canConfirmSelected: boolean;
  draftCount: number;
  collecting: boolean;
  confirming: boolean;
  allSelected: boolean;
  hasSelectable: boolean;
  onSubmitSelected: () => void;
  onSubmitAll: () => void;
  onConfirmSelected: () => void;
  onConfirmAll: () => void;
  onClear: () => void;
  onToggleAll: () => void;
}) {
  const { t } = useTranslation();
  return (
    <CanAct>
      <div role="toolbar" aria-label={t('common.actions')} className="mb-4 flex flex-wrap items-center gap-2">
        {props.hasSelectable ? (
          <label className="flex items-center gap-2 pr-2 text-sm">
            <Checkbox checked={props.allSelected} onCheckedChange={props.onToggleAll} aria-label={t('partner.selectAll')} />
            <span aria-hidden="true">{t('partner.selectAll')}</span>
          </label>
        ) : null}
        {props.selectedCount > 0 ? (
          <>
            <span className="text-sm font-medium" role="status">
              {t('partner.selected', { count: props.selectedCount })}
            </span>
            {props.canSubmitSelected ? (
              <Button type="button" size="sm" onClick={props.onSubmitSelected}>
                {t('partner.submitSelected', { count: props.selectedCount })}
              </Button>
            ) : null}
            {props.canConfirmSelected ? (
              <Button type="button" size="sm" variant="outline" disabled={props.confirming} onClick={props.onConfirmSelected}>
                {t('partner.confirmSelected', { count: props.selectedCount })}
              </Button>
            ) : null}
            <Button type="button" size="sm" variant="ghost" onClick={props.onClear}>
              <X aria-hidden="true" />
              {t('partner.clearSelection')}
            </Button>
          </>
        ) : (
          <>
            {props.draftCount > 0 ? (
              <Button type="button" size="sm" disabled={props.collecting} onClick={props.onSubmitAll}>
                {t('partner.submitAllDrafts', { count: props.draftCount })}
              </Button>
            ) : null}
            <Button type="button" size="sm" variant="outline" disabled={props.confirming} onClick={props.onConfirmAll}>
              {t('partner.confirmAll')}
            </Button>
          </>
        )}
      </div>
    </CanAct>
  );
}

function NoticeBanner({ notice, names, onClose }: { notice: Notice; names: ReadonlyMap<number, string>; onClose: () => void }) {
  const { t } = useTranslation();
  const failed = notice.result.errors;
  const count = notice.kind === 'submitted' ? notice.result.submitted.length : notice.result.confirmed;
  const empty = count === 0 && failed.length === 0 && (notice.kind === 'submitted' || notice.result.expired === 0);
  return (
    <Alert className="mb-4 border-success/40 bg-success/10" role="status">
      <CheckCircle2 aria-hidden="true" className="text-success" />
      <AlertTitle className="flex items-start justify-between gap-2">
        <span>
          {empty ? t('partner.confirmed.none') : t(notice.kind === 'submitted' ? 'partner.submitted.title' : 'partner.confirmed.title', { count })}
        </span>
        <Button type="button" variant="ghost" size="icon" className="-my-1 size-7 shrink-0" onClick={onClose} aria-label={t('common.close')}>
          <X aria-hidden="true" />
        </Button>
      </AlertTitle>
      <AlertDescription>
        {notice.kind === 'submitted' && count > 0 ? <p>{t('partner.submitted.sla')}</p> : null}
        {notice.kind === 'confirmed' && notice.result.expired > 0 ? <p>{t('partner.confirmed.expired', { count: notice.result.expired })}</p> : null}
        {failed.length > 0 ? (
          <div>
            <p>{t(notice.kind === 'submitted' ? 'partner.submitted.failed' : 'partner.confirmed.failed', { count: failed.length })}</p>
            <ul className="list-disc pl-5">
              {failed.slice(0, 5).map((error) => (
                <li key={`${error.id}-${error.code}`}>
                  {names.get(error.id) ?? t('partner.cardNumber', { id: error.id })}: {t(rowErrorKey(notice.kind === 'submitted' ? 'partner.submitted.code' : 'partner.confirmed.code', error.code))}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
