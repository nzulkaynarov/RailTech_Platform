import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';

import type { PartnerIssue, PartnerProductDetail } from '@/api/portal';
import { usePartnerProduct } from '@/api/queries';
import { DetailList, SectionTitle } from '@/components/Details';
import { DetailSkeleton, ErrorState } from '@/components/QueryStates';
import { StatusBadge } from '@/components/StatusBadge';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { formatDateTime } from '@/lib/format';
import { fieldLabelKey } from '@/lib/partnerProducts';
import { cn } from '@/lib/utils';
import { OfferCell } from './OfferCell';

/**
 * Карточка товара партнёра: данные, что исправить после возврата (поле подсвечено, рядом комментарий сотрудника),
 * чего не хватает для публикации, своя цена и история проверок. Поля карточки партнёр здесь не правит — их заполняет
 * прайс (ручная карточка с фото и документами — после пилота).
 */
export function ProductSheet({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { t } = useTranslation();
  const query = usePartnerProduct(id);
  return (
    <Sheet open={id !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl" aria-describedby={undefined}>
        <SheetHeader>
          <SheetTitle className="pr-8 break-words">{query.data?.name ?? t('partner.title')}</SheetTitle>
          <SheetDescription>{t('partner.sheet.description')}</SheetDescription>
        </SheetHeader>
        <div className="flex flex-col gap-5 px-4 pb-6">
          {query.isPending ? (
            <DetailSkeleton />
          ) : query.isError ? (
            <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          ) : (
            <ProductBody product={query.data} />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function ProductBody({ product }: { product: PartnerProductDetail }) {
  const { t, i18n } = useTranslation();
  const issues = new Map<string, PartnerIssue>();
  for (const issue of product.return_issues) if (!issues.has(issue.field)) issues.set(issue.field, issue);
  const value = (field: string, text: string | null | undefined) => <IssueField issue={issues.get(field)}>{text || '—'}</IssueField>;
  const shown = new Set(['name', 'brand', 'manufacturer_part_number', 'category', 'uom', 'hs_code', 'description']);
  const outside = product.return_issues.filter((issue) => !shown.has(issue.field));
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge entity="partner" code={product.status} />
        {product.has_pending_change ? <span className="text-xs text-muted-foreground">{t('partner.pendingChange')}</span> : null}
        <span className="text-xs text-muted-foreground">{t('partner.sheet.completeness', { percent: product.completeness })}</span>
      </div>

      {product.status === 'returned' ? (
        <section aria-labelledby="returned-title" className="flex flex-col gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
          <h3 id="returned-title" className="flex items-center gap-2 font-semibold text-warning">
            <AlertTriangle className="size-4" aria-hidden="true" />
            {t('partner.sheet.issuesTitle')}
          </h3>
          {product.return_reason ? (
            <p>
              <span className="font-medium">{t('partner.sheet.generalComment')}: </span>
              {product.return_reason}
            </p>
          ) : null}
          {outside.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {outside.map((issue) => (
                <li key={issue.field}>
                  <span className="font-medium">{t(fieldLabelKey(issue.field))}: </span>
                  {issue.comment}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="text-xs text-muted-foreground">{t('partner.returnedFixHint')}</p>
        </section>
      ) : null}

      <div>
        <SectionTitle>{t('partner.sheet.fields')}</SectionTitle>
        <DetailList
          items={[
            { label: t(fieldLabelKey('name')), value: value('name', product.name) },
            { label: t(fieldLabelKey('brand')), value: value('brand', product.brand) },
            { label: t(fieldLabelKey('manufacturer_part_number')), value: value('manufacturer_part_number', product.manufacturer_part_number) },
            { label: t(fieldLabelKey('category')), value: value('category', product.category) },
            { label: t(fieldLabelKey('uom')), value: value('uom', product.uom) },
            { label: t(fieldLabelKey('hs_code')), value: value('hs_code', product.hs_code) },
            { label: t(fieldLabelKey('description')), value: value('description', product.description) },
          ]}
        />
        {!product.is_own ? <p className="mt-2 text-xs text-muted-foreground">{t('partner.sheet.foreignNote')}</p> : null}
      </div>

      {product.missing.length > 0 ? (
        <p className="text-sm">
          <span className="font-medium">{t('partner.sheet.missing')}: </span>
          {product.missing.map((item) => t(fieldLabelKey(item.code))).join(', ')}
        </p>
      ) : null}

      <div>
        <SectionTitle>{t('partner.sheet.myPrice')}</SectionTitle>
        <OfferCell offer={product.offer} />
      </div>

      {product.is_own ? (
        <div>
          <SectionTitle>{t('partner.sheet.history')}</SectionTitle>
          {product.history.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('partner.sheet.historyEmpty')}</p>
          ) : (
            <ol className="flex flex-col gap-3">
              {product.history.map((entry) => (
                <li key={entry.submitted_at} className="rounded-lg border p-3 text-sm">
                  <p className="font-medium">{t(`partner.sheet.decision.${entry.decision}`)}</p>
                  <p className="text-xs text-muted-foreground">
                    {t('partner.sheet.submittedAt', { date: formatDateTime(entry.submitted_at, i18n.language) })}
                    {entry.decided_at ? ` · ${t('partner.sheet.decidedAt', { date: formatDateTime(entry.decided_at, i18n.language) })}` : ''}
                  </p>
                  {entry.reason ? <p className="mt-1">{entry.reason}</p> : null}
                  {entry.issues.length > 0 ? (
                    <ul className="mt-1 list-disc pl-5">
                      {entry.issues.map((issue) => (
                        <li key={`${issue.field}-${issue.comment}`}>
                          <span className="font-medium">{t(fieldLabelKey(issue.field))}: </span>
                          {issue.comment}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ol>
          )}
        </div>
      ) : null}
    </>
  );
}

/** Значение поля; если к нему есть замечание сотрудника — рамка и комментарий под значением (подсветка поля). */
function IssueField({ issue, children }: { issue?: PartnerIssue; children: React.ReactNode }) {
  const { t } = useTranslation();
  if (!issue) return <>{children}</>;
  return (
    <div className={cn('rounded-md border border-warning bg-warning/10 px-2 py-1')} data-issue={issue.field}>
      <div>{children}</div>
      <p className="mt-1 text-xs font-medium text-warning">
        <span className="sr-only">{t('partner.sheet.fix')}: </span>
        {issue.comment}
      </p>
    </div>
  );
}
