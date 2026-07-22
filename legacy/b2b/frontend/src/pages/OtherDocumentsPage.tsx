import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { FileSignature, Send, Ban, Mail, Loader2, Inbox } from 'lucide-react';
import { translateApiError } from '@/lib/apiError';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import {
  Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import {
  Toolbar, Pager, useListParams, applyListParams,
} from '@/components/DataTable';
import {
  useGeneratedDocuments, useIssueDocument, useCancelDocument, useUpdateDocumentValues, useSendDocument,
} from '@/hooks/useDocuments';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { DocumentCreateWizard } from '@/components/Documents/DocumentCreateWizard';
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

  const columns: ResponsiveColumn<GeneratedDocument>[] = [
    {
      id: 'number', sortKey: 'number', header: t('otherDocumentsPage.table.number'), mobileTitle: true,
      cell: (doc) => <span className="font-medium">{doc.number}</span>,
    },
    {
      id: 'title', sortKey: 'title', header: t('otherDocumentsPage.table.title'),
      cell: (doc) => doc.title,
    },
    {
      id: 'type', header: t('otherDocumentsPage.table.type'), className: 'text-muted-foreground',
      cell: (doc) => doc.template_name,
    },
    {
      id: 'status', header: t('otherDocumentsPage.table.status'),
      cell: (doc) => (
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={STATUS_VARIANT[doc.status_code]}>
            {t(`otherDocumentsPage.status.${doc.status_code}`)}
          </Badge>
          {doc.is_owned === false && (
            <Badge variant="outline" className="gap-1">
              <Inbox className="size-3" aria-hidden="true" />
              {t('otherDocumentsPage.received')}
            </Badge>
          )}
        </div>
      ),
    },
    {
      id: 'created', sortKey: 'created_at', header: t('otherDocumentsPage.table.created'),
      className: 'text-xs text-muted-foreground',
      cell: (doc) => new Date(doc.created_at).toLocaleDateString(),
    },
    {
      id: 'actions', header: t('otherDocumentsPage.table.actions'), className: 'text-right', mobileActions: true,
      cell: (doc) => (doc.pdf_available ? (
        <DocumentActions
          request={() => ({ path: `crm/generated-documents/${doc.id}/download-pdf/` })}
          filenameBase={`RailTech_Document_${doc.id}`}
          variant="ghost"
          iconOnly
        />
      ) : null),
    },
  ];

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
              searchFields: (d) => [d.number, d.title, d.template_name, d.deal_title ?? ''],
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
                <ResponsiveDataTable
                  columns={columns}
                  rows={pageItems}
                  getRowId={(doc) => doc.id}
                  // Clicking the row opens the document detail sheet (issue / cancel / send / preview).
                  onRowClick={(doc) => setSelectedId(doc.id)}
                  sorting={{ ordering: listParams.ordering, onToggle: listParams.toggleOrdering }}
                />
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
  const [sendOpen, setSendOpen] = useState(false);
  const valueKeys = Object.keys(document.values ?? {});
  const isDraft = document.status_code === 'DRAFT';
  const isIssued = document.status_code === 'ISSUED';
  // A received (counterparty-owned) document is strictly read-only: no issue/cancel/value editing.
  const isReceived = document.is_owned === false;
  const canAct = !isViewer && !isReceived;
  // Public share link: the backend builds it from FRONTEND_URL + minted token and only fills it
  // for ISSUED documents (null otherwise), so use it verbatim.
  const publicLink = isIssued ? document.public_url : null;

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
          <SheetDescription asChild>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant={STATUS_VARIANT[document.status_code]}>
                {t(`otherDocumentsPage.status.${document.status_code}`)}
              </Badge>
              {isReceived && (
                <Badge variant="outline" className="gap-1">
                  <Inbox className="size-3" aria-hidden="true" />
                  {t('otherDocumentsPage.received')}
                </Badge>
              )}
            </div>
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
              `values` keys come from the template placeholders resolved at generation time.
              Received (counterparty) documents are read-only — no value editor. */}
          {isDraft && !isReceived && valueKeys.length > 0 && (
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
            {isIssued && document.pdf_available && (
              <DocumentActions
                request={() => ({ path: `crm/generated-documents/${document.id}/download-pdf/` })}
                filenameBase={`RailTech_Document_${document.id}`}
                publicLink={publicLink ?? undefined}
                size="default"
              />
            )}
            {/* Send by email — owner-only, ISSUED-only (the public link travels in the body). */}
            {isIssued && !isReceived && (
              <Button
                variant="outline"
                disabled={!canAct}
                title={canAct ? undefined : viewerTip}
                onClick={() => setSendOpen(true)}
              >
                <Mail className="mr-2 h-4 w-4" />
                {t('otherDocumentsPage.actions.sendEmail')}
              </Button>
            )}
            {isDraft && !isReceived && (
              <Button disabled={!canAct || busy} title={canAct ? undefined : viewerTip} onClick={onIssue}>
                <Send className="mr-2 h-4 w-4" />
                {t('otherDocumentsPage.actions.issue')}
              </Button>
            )}
            {!isReceived && (isDraft || isIssued) && (
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
      <SendDocumentDialog document={document} open={sendOpen} onOpenChange={setSendOpen} />
    </Sheet>
  );
}

interface SendDocumentDialogProps {
  document: GeneratedDocument;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * F2 II-1 — email an ISSUED document to the counterparty. The email carries the public no-login
 * link (backend `send-email` action, `send_templated_email` — the КП-send pattern). The recipient
 * is pre-filled from the deal contact when the backend can resolve it; leaving it blank lets the
 * backend fall back to the deal contact server-side (NO_RECIPIENT if none exists).
 */
function SendDocumentDialog({ document, open, onOpenChange }: SendDocumentDialogProps) {
  const { t } = useTranslation();
  const sendDocument = useSendDocument();
  const [email, setEmail] = useState<string>(document.recipient_email ?? '');

  const submit = async () => {
    try {
      await sendDocument.mutateAsync({ id: document.id, to: email.trim() || undefined });
      toast.success(t('otherDocumentsPage.sendDialog.sent'));
      onOpenChange(false);
    } catch (error) {
      toast.error(translateApiError(error));
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!sendDocument.isPending) onOpenChange(next); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('otherDocumentsPage.sendDialog.title')}</DialogTitle>
          <DialogDescription>{t('otherDocumentsPage.sendDialog.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="send-doc-email">{t('otherDocumentsPage.sendDialog.emailLabel')}</Label>
          <Input
            id="send-doc-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder={t('otherDocumentsPage.sendDialog.emailPlaceholder')}
            disabled={sendDocument.isPending}
          />
          <p className="text-xs text-muted-foreground">{t('otherDocumentsPage.sendDialog.hint')}</p>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={sendDocument.isPending}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} disabled={sendDocument.isPending}>
            {sendDocument.isPending
              ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
              : <Mail className="mr-2 h-4 w-4" aria-hidden="true" />}
            {t('otherDocumentsPage.sendDialog.submit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default OtherDocumentsPage;
