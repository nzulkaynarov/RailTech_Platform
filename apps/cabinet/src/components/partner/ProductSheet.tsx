import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Download, FileText, Plus, Trash2 } from 'lucide-react';

import { apiErrorKey } from '@/api/errors';
import type { PartnerIssue, PartnerProductDetail, PartnerProductDocument } from '@/api/portal';
import { useDeletePartnerProductDocument, usePartnerProduct, useUploadPartnerProductDocument } from '@/api/queries';
import { DetailList, SectionTitle } from '@/components/Details';
import { DateField } from '@/components/DateField';
import { FileField } from '@/components/FileField';
import { DetailSkeleton, ErrorState } from '@/components/QueryStates';
import { StatusBadge } from '@/components/StatusBadge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { downloadPartnerProductDocument } from '@/lib/download';
import { formatDate, formatDateTime } from '@/lib/format';
import { fieldLabelKey } from '@/lib/partnerProducts';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/utils';
import { CanAct } from '@/session/CanAct';
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
  const [showUpload, setShowUpload] = useState(false);
  const deleteDoc = useDeletePartnerProductDocument();

  const handleDownload = async (doc: PartnerProductDocument) => {
    try {
      await downloadPartnerProductDocument(product.id, doc.id, `${doc.title}.pdf`);
    } catch {
      toast.error(t('common.loadFailed'));
    }
  };

  const handleDelete = (docId: number, docTitle: string) => {
    if (!window.confirm(t('partner.sheet.deleteConfirm', { name: docTitle }))) return;
    deleteDoc.mutate(
      { productId: product.id, docId },
      {
        onSuccess: () => {
          toast.success(t('common.save'));
        },
        onError: (err) => {
          toast.error(t(apiErrorKey(err)));
        },
      },
    );
  };

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
        {product.status === 'matched' ? null : (
          <span className="text-xs text-muted-foreground">{t('partner.sheet.completeness', { percent: product.completeness })}</span>
        )}
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
            // У сопоставленной чужой карточки остальных данных кабинет не получает — строки не рисуем
            ...(product.status === 'matched'
              ? []
              : [
                  { label: t(fieldLabelKey('category')), value: value('category', product.category) },
                  { label: t(fieldLabelKey('uom')), value: value('uom', product.uom) },
                  { label: t(fieldLabelKey('hs_code')), value: value('hs_code', product.hs_code) },
                  { label: t(fieldLabelKey('description')), value: value('description', product.description) },
                ]),
          ]}
        />
        {!product.is_own ? <p className="mt-2 text-xs text-muted-foreground">{t('partner.sheet.foreignNote')}</p> : null}
      </div>

      {/* Документы и сертификаты товара */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <SectionTitle>{t('partner.sheet.documentsTitle')}</SectionTitle>
          <CanAct>
            {product.is_own ? (
              <Button size="sm" variant="outline" className="text-xs" onClick={() => setShowUpload(true)}>
                <Plus className="mr-1 size-3.5" aria-hidden="true" />
                {t('partner.sheet.addDocument')}
              </Button>
            ) : null}
          </CanAct>
        </div>
        {product.documents.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('partner.sheet.documentsEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {product.documents.map((doc) => (
              <li key={doc.id} className="flex items-center justify-between rounded-lg border p-2.5 text-sm">
                <div className="min-w-0 flex-1 pr-2">
                  <div className="flex items-center gap-2">
                    <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <span className="font-medium truncate">{doc.title}</span>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{doc.kind_name}</span>
                    {doc.status !== 'approved' ? (
                      <span
                        data-testid={`doc-status-${doc.status}`}
                        title={doc.status === 'pending' ? t('partner.sheet.docStatus.pendingHint') : undefined}
                        className={
                          doc.status === 'rejected'
                            ? 'rounded bg-destructive/10 px-1.5 py-0.5 text-xs text-destructive'
                            : 'rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-xs text-warning'
                        }
                      >
                        {t(`partner.sheet.docStatus.${doc.status}`)}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {doc.number ? `${t('partner.sheet.docNumber')}: ${doc.number} · ` : ''}
                    {doc.valid_until
                      ? t('partner.sheet.validUntil', { date: formatDate(doc.valid_until, i18n.language) })
                      : t('partner.sheet.unlimited')}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void handleDownload(doc)}
                    aria-label={t('partner.sheet.downloadDoc', { name: doc.title })}
                  >
                    <Download className="size-4" aria-hidden="true" />
                  </Button>
                  <CanAct>
                    {product.is_own && doc.can_delete ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive hover:text-destructive"
                        onClick={() => handleDelete(doc.id, doc.title)}
                        disabled={deleteDoc.isPending}
                        aria-label={t('partner.sheet.deleteDoc', { name: doc.title })}
                      >
                        <Trash2 className="size-4" aria-hidden="true" />
                      </Button>
                    ) : null}
                  </CanAct>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <UploadDocumentDialog
        productId={product.id}
        open={showUpload}
        onOpenChange={setShowUpload}
      />

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

function UploadDocumentDialog({
  productId,
  open,
  onOpenChange,
}: {
  productId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<string>('certificate');
  const [title, setTitle] = useState('');
  const [number, setNumber] = useState('');
  const [validUntil, setValidUntil] = useState<string | null>(null);
  const uploadDoc = useUploadPartnerProductDocument();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !title.trim()) return;

    uploadDoc.mutate(
      {
        productId,
        data: {
          file,
          kind,
          title: title.trim(),
          number: number.trim() || undefined,
          valid_until: validUntil || undefined,
        },
      },
      {
        onSuccess: () => {
          toast.success(t('common.save'));
          onOpenChange(false);
          setFile(null);
          setKind('certificate');
          setTitle('');
          setNumber('');
          setValidUntil(null);
        },
        onError: (err) => {
          toast.error(t(apiErrorKey(err)));
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('partner.sheet.uploadDialog.title')}</DialogTitle>
          <DialogDescription>{t('partner.sheet.uploadDialog.description')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2">
          <div>
            <Label htmlFor="doc-file">{t('partner.sheet.uploadDialog.file')} *</Label>
            <div className="mt-1">
              <FileField
                id="doc-file"
                value={file}
                accept=".pdf,.png,.jpg,.jpeg"
                onChange={(f) => {
                  setFile(f);
                  if (f && !title) {
                    setTitle(f.name.replace(/\.[^/.]+$/, ''));
                  }
                }}
              />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{t('partner.sheet.uploadDialog.fileHint')}</p>
          </div>
          <div>
            <Label htmlFor="doc-kind">{t('partner.sheet.uploadDialog.kind')}</Label>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger id="doc-kind" className="mt-1 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="certificate">{t('partner.sheet.uploadDialog.kinds.certificate')}</SelectItem>
                <SelectItem value="passport">{t('partner.sheet.uploadDialog.kinds.passport')}</SelectItem>
                <SelectItem value="declaration">{t('partner.sheet.uploadDialog.kinds.declaration')}</SelectItem>
                <SelectItem value="other">{t('partner.sheet.uploadDialog.kinds.other')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="doc-title">{t('partner.sheet.uploadDialog.docTitle')} *</Label>
            <Input
              id="doc-title"
              className="mt-1"
              placeholder={t('partner.sheet.uploadDialog.docTitlePlaceholder')}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="doc-number">{t('partner.sheet.uploadDialog.number')}</Label>
            <Input
              id="doc-number"
              className="mt-1"
              placeholder={t('partner.sheet.uploadDialog.numberPlaceholder')}
              value={number}
              onChange={(e) => setNumber(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="doc-valid-until">{t('partner.sheet.uploadDialog.validUntil')}</Label>
            <div className="mt-1">
              <DateField
                id="doc-valid-until"
                value={validUntil}
                onChange={setValidUntil}
              />
            </div>
          </div>
          <DialogFooter className="gap-2 pt-2">
            <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" size="sm" disabled={!file || !title.trim() || uploadDoc.isPending}>
              {uploadDoc.isPending ? t('partner.sheet.uploadDialog.uploading') : t('partner.sheet.uploadDialog.upload')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
