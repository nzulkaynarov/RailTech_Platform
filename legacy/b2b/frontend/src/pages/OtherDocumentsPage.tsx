import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { FileSignature, Send, Ban } from 'lucide-react';
import { translateApiError } from '@/lib/apiError';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import {
  Toolbar, SortableHead, Pager, useListParams, applyListParams,
} from '@/components/DataTable';
import {
  useGeneratedDocuments, useIssueDocument, useCancelDocument, useUpdateDocumentValues,
} from '@/hooks/useDocuments';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { DocumentCreateWizard } from '@/components/Documents/DocumentCreateWizard';
import { openableRowProps } from '@/lib/rowClick';
import { DealLink } from '@/components/Shared/DealLink';
import type { GeneratedDocument, GeneratedDocumentStatus } from '@/api/documentsApi';

const STATUS_VARIANT: Record<GeneratedDocumentStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  DRAFT: 'secondary',
  ISSUED: 'default',
  CANCELLED: 'destructive',
};
const STATUS_CODES: GeneratedDocumentStatus[] = ['DRAFT', 'ISSUED', 'CANCELLED'];

export function OtherDocumentsPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['status'] as const, { defaultOrdering: '-created_at' });
  const { data: documents, isLoading, isError, refetch } = useGeneratedDocuments(undefined);
  const issueDocument = useIssueDocument();
  const cancelDocument = useCancelDocument();
  const updateValues = useUpdateDocumentValues();
  const isViewer = useIsViewerMode();
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');
  const [wizardOpen, setWizardOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = useMemo(
    () => (documents ?? []).find((d) => d.id === selectedId) ?? null,
    [documents, selectedId],
  );

  const stats = useMemo(() => {
    const list = documents ?? [];
    return [
      { label: t('otherDocumentsPage.stats.total'), value: String(list.length) },
      { label: t('otherDocumentsPage.stats.draft'), value: String(list.filter((d) => d.status_code === 'DRAFT').length) },
      { label: t('otherDocumentsPage.stats.issued'), value: String(list.filter((d) => d.status_code === 'ISSUED').length) },
    ];
  }, [documents, t]);

  const onIssue = async (id: number) => {
    try {
      await issueDocument.mutateAsync(id);
      toast.success(t('otherDocumentsPage.issued'));
    } catch (error) {
      toast.error(translateApiError(error));
    }
  };

  const onCancel = async (id: number) => {
    try {
      await cancelDocument.mutateAsync(id);
      toast.success(t('otherDocumentsPage.cancelled'));
    } catch (error) {
      toast.error(translateApiError(error));
    }
  };

  return (
    <PageShell
      title={t('otherDocumentsPage.title')}
      description={t('otherDocumentsPage.description')}
      icon={<FileSignature className="h-5 w-5" />}
      stats={stats}
      actions={[
        {
          label: t('documentsHub.create'),
          onClick: () => setWizardOpen(true),
          disabled: isViewer,
        },
      ]}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('otherDocumentsPage.searchPlaceholder')}
        filters={[
          {
            key: 'status',
            value: listParams.filters.status,
            onChange: (v) => listParams.setFilter('status', v),
            allLabel: t('otherDocumentsPage.allStatuses'),
            options: STATUS_CODES.map((s) => ({ value: s, label: t(`otherDocumentsPage.status.${s}`) })),
          },
        ]}
      />
      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(documents ?? [], listParams, {
              searchFields: (d) => [d.number, d.title, d.template_name],
              filterPredicates: { status: (d, v) => d.status_code === v },
              sortAccessors: {
                number: (d) => d.number,
                title: (d) => d.title,
                created_at: (d) => d.created_at,
              },
            });
            if (isLoading) return <LoadingRows rows={6} />;
            if (isError) return <ErrorState onRetry={refetch} />;
            if (!pageItems.length) {
              // Documents are created from the «Создать документ» action (wave A3) or from a deal —
              // the empty state points there so the list is never a dead-end.
              return (
                <EmptyState
                  icon={<FileSignature className="h-5 w-5" />}
                  message={t('otherDocumentsPage.emptyState')}
                  hint={t('otherDocumentsPage.emptyStateHint')}
                />
              );
            }
            return (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead sortKey="number" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('otherDocumentsPage.table.number')}
                      </SortableHead>
                      <SortableHead sortKey="title" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('otherDocumentsPage.table.title')}
                      </SortableHead>
                      <TableHead>{t('otherDocumentsPage.table.type')}</TableHead>
                      <TableHead>{t('otherDocumentsPage.table.status')}</TableHead>
                      <SortableHead sortKey="created_at" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('otherDocumentsPage.table.created')}
                      </SortableHead>
                      <TableHead className="text-right">{t('otherDocumentsPage.table.actions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pageItems.map((doc) => (
                      <TableRow
                        key={doc.id}
                        {...openableRowProps(() => setSelectedId(doc.id), `${t('common.open')} ${doc.number}`)}
                      >
                        <TableCell className="font-medium">{doc.number}</TableCell>
                        <TableCell>{doc.title}</TableCell>
                        <TableCell className="text-muted-foreground">{doc.template_name}</TableCell>
                        <TableCell>
                          <Badge variant={STATUS_VARIANT[doc.status_code]}>
                            {t(`otherDocumentsPage.status.${doc.status_code}`)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {new Date(doc.created_at).toLocaleDateString()}
                        </TableCell>
                        <TableCell className="text-right" data-row-action>
                          {doc.pdf_available && (
                            <DocumentActions
                              request={() => ({ path: `crm/generated-documents/${doc.id}/download-pdf/` })}
                              filenameBase={`RailTech_Document_${doc.id}`}
                              variant="ghost"
                              iconOnly
                            />
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
              </>
            );
          })()}
        </CardContent>
      </Card>

      <DocumentCreateWizard open={wizardOpen} onOpenChange={setWizardOpen} />

      {selected && (
        <DocumentSheet
          document={selected}
          isViewer={isViewer}
          viewerTip={viewerTip}
          busy={issueDocument.isPending || cancelDocument.isPending || updateValues.isPending}
          onClose={() => setSelectedId(null)}
          onIssue={() => onIssue(selected.id)}
          onCancel={() => onCancel(selected.id)}
          onSaveValues={updateValues}
        />
      )}
    </PageShell>
  );
}

interface DocumentSheetProps {
  document: GeneratedDocument;
  isViewer: boolean;
  viewerTip: string;
  busy: boolean;
  onClose: () => void;
  onIssue: () => void;
  onCancel: () => void;
  onSaveValues: ReturnType<typeof useUpdateDocumentValues>;
}

function DocumentSheet({
  document, isViewer, viewerTip, busy, onClose, onIssue, onCancel, onSaveValues,
}: DocumentSheetProps) {
  const { t } = useTranslation();
  const [values, setValues] = useState<Record<string, string>>(() => ({ ...(document.values ?? {}) }));
  const valueKeys = Object.keys(document.values ?? {});
  const isDraft = document.status_code === 'DRAFT';
  const canAct = !isViewer;

  const onSave = async () => {
    try {
      await onSaveValues.mutateAsync({ id: document.id, values });
      toast.success(t('otherDocumentsPage.valuesSaved'));
    } catch (error) {
      toast.error(translateApiError(error));
    }
  };

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{document.number}</SheetTitle>
          <SheetDescription>
            <Badge variant={STATUS_VARIANT[document.status_code]}>
              {t(`otherDocumentsPage.status.${document.status_code}`)}
            </Badge>
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-4 p-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <Label>{t('otherDocumentsPage.table.title')}</Label>
              <p className="text-foreground">{document.title}</p>
            </div>
            <div>
              <Label>{t('otherDocumentsPage.table.type')}</Label>
              <p className="text-muted-foreground">{document.template_name}</p>
            </div>
            <div>
              <Label>{t('otherDocumentsPage.table.deal')}</Label>
              {document.deal ? <DealLink dealId={document.deal} /> : <p className="text-muted-foreground">—</p>}
            </div>
            <div>
              <Label>{t('otherDocumentsPage.table.contact')}</Label>
              <p className="text-muted-foreground">{document.contact_name || '—'}</p>
            </div>
            <div>
              <Label>{t('otherDocumentsPage.table.created')}</Label>
              <p className="text-muted-foreground">{new Date(document.created_at).toLocaleString()}</p>
            </div>
            <div>
              <Label>{t('otherDocumentsPage.table.issued')}</Label>
              <p className="text-muted-foreground">
                {document.issued_at ? new Date(document.issued_at).toLocaleString() : '—'}
              </p>
            </div>
          </div>

          {/* DRAFT placeholder-value editing (re-render + PDF invalidation on the backend).
              `values` keys come from the template placeholders resolved at generation time. */}
          {isDraft && valueKeys.length > 0 && (
            <div className="space-y-3 rounded-md border border-border p-3">
              <p className="text-sm font-medium">{t('otherDocumentsPage.valuesTitle')}</p>
              {valueKeys.map((key) => (
                <div key={key} className="space-y-1">
                  <Label htmlFor={`value-${key}`} className="text-xs text-muted-foreground">{key}</Label>
                  <Input
                    id={`value-${key}`}
                    value={values[key] ?? ''}
                    disabled={!canAct || busy}
                    onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
                  />
                </div>
              ))}
              <Button
                variant="outline"
                size="sm"
                disabled={!canAct || busy}
                title={canAct ? undefined : viewerTip}
                onClick={onSave}
              >
                {t('otherDocumentsPage.saveValues')}
              </Button>
            </div>
          )}

          {/* Preview: `rendered_html` is sanitised server-side by an allowlist sanitiser
              (crm.services strips scripts/handlers), so it is safe to inject here. */}
          <div>
            <Label>{t('otherDocumentsPage.previewTitle')}</Label>
            <div
              className="mt-2 max-h-[40vh] overflow-auto rounded-md border border-border bg-muted/30 p-4 text-sm leading-relaxed text-foreground"
              // rendered_html is sanitised server-side by the crm.services allowlist sanitiser
              // (scripts/handlers stripped) before it is ever returned — safe to inject.
              dangerouslySetInnerHTML={{ __html: document.rendered_html }}
            />
          </div>

          <div className="flex flex-col gap-2">
            {document.status_code === 'ISSUED' && document.pdf_available && (
              <DocumentActions
                request={() => ({ path: `crm/generated-documents/${document.id}/download-pdf/` })}
                filenameBase={`RailTech_Document_${document.id}`}
                size="default"
              />
            )}
            {isDraft && (
              <Button disabled={!canAct || busy} title={canAct ? undefined : viewerTip} onClick={onIssue}>
                <Send className="mr-2 h-4 w-4" />
                {t('otherDocumentsPage.actions.issue')}
              </Button>
            )}
            {(document.status_code === 'DRAFT' || document.status_code === 'ISSUED') && (
              <Button
                variant="outline"
                disabled={!canAct || busy}
                title={canAct ? undefined : viewerTip}
                onClick={onCancel}
              >
                <Ban className="mr-2 h-4 w-4" />
                {t('otherDocumentsPage.actions.cancel')}
              </Button>
            )}
          </div>
        </div>
        <SheetFooter />
      </SheetContent>
    </Sheet>
  );
}

export default OtherDocumentsPage;
