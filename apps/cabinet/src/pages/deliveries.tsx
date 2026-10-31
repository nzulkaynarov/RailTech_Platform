import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, FolderOpen, Loader2, Search, Truck } from 'lucide-react';
import { toast } from '@/lib/toast';

import { apiErrorKey } from '@/api/errors';
import type { DeliveryLine, DocumentKind, PortalDocument } from '@/api/portal';
import { useAcceptDelivery, useDeliveries, useDisputeDelivery, useDocuments } from '@/api/queries';
import { DealLink } from '@/components/Details';
import { DocumentButton } from '@/components/DocumentButton';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ReasonDialog } from '@/components/ReasonDialog';
import { ResponsiveList } from '@/components/ResponsiveList';
import { StatusBadge } from '@/components/StatusBadge';
import { ManagerButton } from '@/components/TelegramLinkButton';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { groupDeliveries } from '@/lib/deliveries';
import { DOCUMENT_KINDS, isDocumentKind } from '@/lib/documents';
import { formatDate, formatDateTime, formatFileSize, formatQuantity } from '@/lib/format';
import { cn } from '@/lib/utils';
import { BillingNavTabs } from '@/pages/billing';
import { CanAct } from '@/session/CanAct';

/**
 * Поставки по строкам (B2B `FulfillmentsPage` как основа; статусы — проекция ERP, M4-ERP-04) и
 * документы компании (B2B `CompanyFilesPage`). Поставки сгруппированы по сделке: клиент думает
 * «мой заказ», а не «строка 2». Поставщиков, цен и складов здесь нет — их нет и в контракте.
 * Приёмка по строкам настоящая: «Принять» → `POST /deliveries/{id}/accept`, «Замечание» →
 * `/dispute {reason}`; кнопки есть только у строки в статусе `delivered`.
 */
export function DeliveriesPage() {
  const { t } = useTranslation();
  const deliveries = useDeliveries();
  const accept = useAcceptDelivery();
  const dispute = useDisputeDelivery();
  const [disputeTarget, setDisputeTarget] = useState<DeliveryLine | null>(null);
  const [acceptingId, setAcceptingId] = useState<number | null>(null);

  const acceptLine = (line: DeliveryLine) => {
    setAcceptingId(line.id);
    accept.mutate(line.id, {
      onSuccess: () => toast.success(t('pages.deliveries.lineAcceptedToast', { name: line.title })),
      onError: (error) => toast.error(t(apiErrorKey(error))),
      onSettled: () => setAcceptingId(null),
    });
  };

  const closeDispute = () => {
    setDisputeTarget(null);
    dispute.reset();
  };

  return (
    <>
      <PageHeader title={t('pages.deliveries.title')} icon={Truck} />
      {deliveries.isPending ? (
        <ListSkeleton />
      ) : deliveries.isError ? (
        <ErrorState error={deliveries.error} onRetry={() => void deliveries.refetch()} />
      ) : deliveries.data.length === 0 ? (
        <EmptyState icon={Truck} title={t('pages.deliveries.emptyTitle')} text={t('pages.deliveries.emptyText')} />
      ) : (
        <div className="flex flex-col gap-4">
          {groupDeliveries(deliveries.data).map((group) => (
            <Card key={group.deal.id} className="gap-3 py-4">
              <CardHeader className="flex flex-wrap items-center justify-between gap-2 px-4">
                <CardTitle className="min-w-0">
                  <h2 className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-base">
                    <DealLink deal={group.deal} showTitle stackTitle />
                    <span className="text-sm font-normal text-muted-foreground">
                      {t('pages.deliveries.progress', { done: group.delivered, total: group.lines.length })}
                    </span>
                  </h2>
                </CardTitle>
                <ManagerButton dealId={group.deal.id} label={t('manager.aboutDeal', { number: group.deal.number })} />
              </CardHeader>
              <CardContent className="px-4">
                <ul className="flex flex-col divide-y" aria-label={t('common.dealNumber', { number: group.deal.number })}>
                  {group.lines.map((line) => (
                    <li key={line.id} className="flex min-w-0 flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between">
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <span className="text-sm font-medium wrap-break-word">{line.title}</span>
                        <span className="text-xs text-muted-foreground">{formatQuantity(line.quantity, line.unit)}</span>
                      </div>
                      <div className="flex min-w-0 flex-col gap-1 text-sm sm:items-end sm:text-right">
                        <StatusBadge entity="delivery" code={line.status} />
                        {RECEIVED_STATUSES.includes(line.status) || line.status === 'shipped' ? null : (
                          <span className="text-muted-foreground">
                            {line.eta ? t('pages.deliveries.eta', { date: formatDate(line.eta) }) : t('pages.deliveries.etaUnknown')}
                          </span>
                        )}
                        {line.shipped_at ? (
                          <span className="text-muted-foreground">{t('pages.deliveries.shippedAt', { date: formatDateTime(line.shipped_at) })}</span>
                        ) : null}
                        {line.tracking ? (
                          <span className="break-all">
                            {t('pages.deliveries.tracking')}: <span className="font-mono">{line.tracking}</span>
                          </span>
                        ) : null}
                        {line.status === 'accepted' && line.accepted_at ? (
                          <span className="text-muted-foreground">{t('pages.deliveries.acceptedAt', { date: formatDateTime(line.accepted_at) })}</span>
                        ) : null}
                        {line.status === 'disputed' ? (
                          <span className="flex flex-col gap-0.5 text-muted-foreground">
                            {line.accepted_at ? <span>{t('pages.deliveries.disputedAt', { date: formatDateTime(line.accepted_at) })}</span> : null}
                            {line.remark ? <span className="wrap-break-word">{t('pages.deliveries.remark', { remark: line.remark })}</span> : null}
                          </span>
                        ) : null}
                        {line.status === 'delivered' ? (
                          <CanAct>
                            <div className="mt-1 flex flex-wrap items-center gap-1 sm:justify-end">
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={acceptingId === line.id}
                                onClick={() => acceptLine(line)}
                                aria-label={t('pages.deliveries.acceptLineNamed', { name: line.title })}
                              >
                                {acceptingId === line.id ? <Loader2 className="animate-spin" aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />}
                                {t('pages.deliveries.acceptLine')}
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                disabled={acceptingId === line.id}
                                onClick={() => setDisputeTarget(line)}
                                aria-label={t('pages.deliveries.disputeLineNamed', { name: line.title })}
                              >
                                <AlertTriangle aria-hidden="true" />
                                {t('pages.deliveries.disputeLine')}
                              </Button>
                            </div>
                          </CanAct>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      <ReasonDialog
        target={disputeTarget?.id ?? null}
        open={Boolean(disputeTarget)}
        onOpenChange={(open) => !open && closeDispute()}
        title={t('pages.deliveries.disputeTitle', { name: disputeTarget?.title ?? '' })}
        description={t('pages.deliveries.disputeText')}
        label={t('pages.deliveries.disputeReason')}
        placeholder={t('pages.deliveries.disputePlaceholder')}
        confirmLabel={t('pages.deliveries.disputeConfirm')}
        pending={dispute.isPending}
        error={dispute.error}
        onConfirm={(reason) =>
          disputeTarget &&
          dispute.mutate(
            { id: disputeTarget.id, reason },
            {
              onSuccess: () => {
                toast.success(t('pages.deliveries.disputeSentToast'));
                closeDispute();
              },
            },
          )
        }
      />
    </>
  );
}

/** Доставлено клиенту: ожидаемая дата уже не нужна. */
const RECEIVED_STATUSES: ReadonlyArray<DeliveryLine['status']> = ['delivered', 'accepted', 'disputed'];

export function DocumentsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState('');
  const rawKind = params.get('kind');
  const kind: DocumentKind | undefined = isDocumentKind(rawKind) ? rawKind : undefined;
  const documents = useDocuments(kind ? { kind } : {});

  const filtered = useMemo(() => {
    if (!documents.data) return [];
    if (!query.trim()) return documents.data;
    const q = query.toLowerCase().trim();
    return documents.data.filter((doc) =>
      doc.title.toLowerCase().includes(q) ||
      (doc.number && doc.number.toLowerCase().includes(q)) ||
      (doc.deal && doc.deal.number.toLowerCase().includes(q)),
    );
  }, [documents.data, query]);

  const choose = (next: DocumentKind | undefined) =>
    setParams(
      (current) => {
        const copy = new URLSearchParams(current);
        if (next) copy.set('kind', next);
        else copy.delete('kind');
        return copy;
      },
      { replace: true },
    );

  return (
    <>
      <PageHeader title={t('pages.documents.title')} icon={FolderOpen} />
      <BillingNavTabs />
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div role="group" aria-label={t('pages.documents.filter')} className="flex flex-wrap gap-2">
          {[undefined, ...DOCUMENT_KINDS].map((option) => (
            <Button
              key={option ?? 'all'}
              type="button"
              size="sm"
              variant={option === kind ? 'default' : 'outline'}
              aria-pressed={option === kind}
              className={cn('rounded-full')}
              onClick={() => choose(option)}
            >
              {option ? t(`documents.kinds.${option}`) : t('common.all')}
            </Button>
          ))}
        </div>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('pages.documents.searchPlaceholder')}
            aria-label={t('pages.documents.searchLabel')}
            className="pl-9"
          />
        </div>
      </div>
      {documents.isPending ? (
        <ListSkeleton />
      ) : documents.isError ? (
        <ErrorState error={documents.error} onRetry={() => void documents.refetch()} />
      ) : documents.data.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          title={kind ? t('pages.documents.emptyKindTitle') : t('pages.documents.emptyTitle')}
          text={kind ? t('pages.documents.emptyKindText') : t('pages.documents.emptyText')}
        >
          {kind ? (
            <Button variant="outline" onClick={() => choose(undefined)}>
              {t('pages.documents.showAll')}
            </Button>
          ) : null}
        </EmptyState>
      ) : filtered.length === 0 ? (
        <EmptyState icon={Search} title={t('pages.documents.noMatchTitle')} text={t('pages.documents.noMatchText', { query: query.trim() })}>
          <Button variant="outline" onClick={() => setQuery('')}>
            {t('pages.documents.clearSearch')}
          </Button>
        </EmptyState>
      ) : (
        <ResponsiveList<PortalDocument>
          label={t('pages.documents.title')}
          rows={filtered}
          getRowId={(row) => row.id}
          title={{ header: t('pages.documents.columns.document'), cell: (row) => <span className="font-medium">{row.title}</span> }}
          columns={[
            { id: 'kind', header: t('pages.documents.columns.kind'), cell: (row) => t(`documents.kinds.${row.kind}`) },
            { id: 'date', header: t('pages.documents.columns.date'), cell: (row) => formatDate(row.date) },
            { id: 'size', header: t('pages.documents.columns.size'), cell: (row) => formatFileSize(row.size_bytes) },
            { id: 'deal', header: t('pages.documents.columns.deal'), cell: (row) => <DealLink deal={row.deal} /> },
          ]}
          actions={{
            header: t('common.actions'),
            cell: (row) => <DocumentButton documentId={row.id} fileName={row.file_name ?? `${row.number}.pdf`} label={row.title} />,
          }}
        />
      )}
    </>
  );
}
