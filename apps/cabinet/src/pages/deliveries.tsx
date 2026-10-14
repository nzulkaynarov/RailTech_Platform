import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FolderOpen, Truck } from 'lucide-react';

import type { DocumentKind, PortalDocument } from '@/api/portal';
import { useDeliveries, useDocuments } from '@/api/queries';
import { DealLink } from '@/components/Details';
import { DocumentButton } from '@/components/DocumentButton';
import { EmptyState } from '@/components/EmptyState';
import { PageHeader } from '@/components/PageHeader';
import { ErrorState, ListSkeleton } from '@/components/QueryStates';
import { ResponsiveList } from '@/components/ResponsiveList';
import { StatusBadge } from '@/components/StatusBadge';
import { ManagerButton } from '@/components/TelegramLinkButton';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { groupDeliveries } from '@/lib/deliveries';
import { DOCUMENT_KINDS, isDocumentKind } from '@/lib/documents';
import { formatDate, formatDateTime, formatFileSize, formatQuantity } from '@/lib/format';
import { cn } from '@/lib/utils';

/**
 * Поставки по строкам (B2B `FulfillmentsPage` как основа; статусы — проекция ERP, M4-ERP-04) и
 * документы компании (B2B `CompanyFilesPage`). Поставки сгруппированы по сделке: клиент думает
 * «мой заказ», а не «строка 2». Поставщиков, цен и складов здесь нет — их нет и в контракте.
 */
export function DeliveriesPage() {
  const { t } = useTranslation();
  const deliveries = useDeliveries();
  return (
    <>
      <PageHeader title={t('pages.deliveries.title')} />
      {deliveries.isPending ? (
        <ListSkeleton />
      ) : deliveries.isError ? (
        <ErrorState error={deliveries.error} onRetry={() => void deliveries.refetch()} />
      ) : deliveries.data.length === 0 ? (
        <EmptyState icon={Truck} title={t('pages.deliveries.emptyTitle')} text={t('pages.deliveries.emptyText')} />
      ) : (
        <div className="flex flex-col gap-4">
          {groupDeliveries(deliveries.data).map((group) => (
            <Card key={group.dealId} className="gap-3 py-4">
              <CardHeader className="flex flex-wrap items-center justify-between gap-2 px-4">
                <CardTitle className="min-w-0">
                  <h2 className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-base">
                    <DealLink dealId={group.dealId} />
                    <span className="text-sm font-normal text-muted-foreground">
                      {t('pages.deliveries.progress', { done: group.delivered, total: group.lines.length })}
                    </span>
                  </h2>
                </CardTitle>
                <ManagerButton dealId={group.dealId} label={t('manager.aboutDeal', { id: group.dealId })} />
              </CardHeader>
              <CardContent className="px-4">
                <ul className="flex flex-col divide-y" aria-label={t('common.dealNumber', { id: group.dealId })}>
                  {group.lines.map((line) => (
                    <li key={line.line_no} className="flex min-w-0 flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between">
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <span className="text-sm font-medium break-words">{line.title}</span>
                        <span className="text-xs text-muted-foreground">{formatQuantity(line.quantity, line.unit)}</span>
                      </div>
                      <div className="flex min-w-0 flex-col gap-1 text-sm sm:items-end sm:text-right">
                        <StatusBadge entity="delivery" code={line.status} />
                        {line.status === 'delivered' || line.status === 'shipped' ? null : (
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
                      </div>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}

export function DocumentsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const rawKind = params.get('kind');
  const kind: DocumentKind | undefined = isDocumentKind(rawKind) ? rawKind : undefined;
  const documents = useDocuments(kind ? { kind } : {});

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
      <PageHeader title={t('pages.documents.title')} />
      <div role="group" aria-label={t('pages.documents.filter')} className="mb-4 flex flex-wrap gap-2">
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
      ) : (
        <ResponsiveList<PortalDocument>
          label={t('pages.documents.title')}
          rows={documents.data}
          getRowId={(row) => row.id}
          title={{ header: t('pages.documents.columns.document'), cell: (row) => <span className="font-medium">{row.title}</span> }}
          columns={[
            { id: 'kind', header: t('pages.documents.columns.kind'), cell: (row) => t(`documents.kinds.${row.kind}`) },
            { id: 'date', header: t('pages.documents.columns.date'), cell: (row) => formatDate(row.date) },
            { id: 'size', header: t('pages.documents.columns.size'), cell: (row) => formatFileSize(row.size_bytes) },
            { id: 'deal', header: t('pages.documents.columns.deal'), cell: (row) => <DealLink dealId={row.deal_id} /> },
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
