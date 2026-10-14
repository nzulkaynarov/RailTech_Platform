import { useMemo, useRef } from 'react'; import { useTranslation } from 'react-i18next'; import { toast } from 'sonner'; import { FolderOpen, Download, FileText } from 'lucide-react'; import { extractBlobErrorCode, fetchDocumentBlob, saveBlob } from '@/lib/documents'; import { formatDate } from '@/lib/formatLocale'; import { translateApiError } from '@/lib/apiError'; import { Card, CardContent } from '@/components/ui/card'; import { Badge } from '@/components/ui/badge'; import { Button } from '@/components/ui/button'; import { ResponsiveDataTable, type ResponsiveColumn } from '@/components/ResponsiveDataTable'; import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell'; import {   Toolbar, Pager } from '@/components/DataTable';
import { useListParams, applyListParams } from '@/components/DataTable/listParams';
import { useCompanyAttachments, useUploadCompanyFile } from '@/hooks/useSourcing';
import { useUserStore } from '@/store/userStore';
import { DealLink } from '@/components/Shared/DealLink';
import type { Attachment } from '@/api/sourcingApi';

// Same extension set the backend `validate_document_upload` accepts (magic-byte checked).
const UPLOAD_ACCEPT = '.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.jpg,.jpeg,.png,.gif,.webp';

type AttachmentKind = NonNullable<Attachment['kind']>;

const KIND_VARIANT: Record<AttachmentKind, 'default' | 'secondary'> = {
  SOURCE: 'secondary',
  SUPPORTING: 'default',
};
const KIND_CODES: AttachmentKind[] = ['SOURCE', 'SUPPORTING'];

export function CompanyFilesPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['kind'] as const, { urlKey: 'company-files', defaultOrdering: '-uploaded_at' });
  const { data: attachments, isLoading, isError, refetch } = useCompanyAttachments();
  const companyId = useUserStore((s) => s.company.id);
  const uploadFile = useUploadCompanyFile();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const onUploadSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Reset the input so re-selecting the SAME file still fires `onChange`.
    event.target.value = '';
    if (!file || companyId == null) return;
    try {
      await uploadFile.mutateAsync({ companyId, file });
      await refetch();
      toast.success(t('companyFilesPage.uploaded'));
    } catch (err) {
      // Surfaces the real backend code (magic-byte reject / extension / size) via translateApiError.
      toast.error(translateApiError(err));
    }
  };

  const stats = useMemo(() => {
    const list = attachments ?? [];
    // `documents` counts every non-SOURCE file (SUPPORTING + records with a null kind — legacy
    // uploads predating the kind field) so sources + documents always equals total; otherwise
    // null-kind rows would vanish from both buckets and the tiles wouldn't reconcile.
    return [
      { label: t('companyFilesPage.stats.total'), value: String(list.length) },
      { label: t('companyFilesPage.stats.sources'), value: String(list.filter((a) => a.kind === 'SOURCE').length) },
      { label: t('companyFilesPage.stats.documents'), value: String(list.filter((a) => a.kind !== 'SOURCE').length) },
    ];
  }, [attachments, t]);

  const onDownload = async (file: Attachment) => {
    try {
      const blob = await fetchDocumentBlob(`sourcing/attachments/${file.id}/download/`);
      saveBlob(blob, file.original_filename || `File_${file.id}`);
    } catch (err) {
      // Surface the real backend code (403/404/expiry) instead of a generic message. Blob-response
      // error bodies aren't plain JSON — parse the code out first, fall back to the generic string.
      const code = await extractBlobErrorCode(err);
      toast.error(code ? translateApiError(code) : t('errors.operationFailed'));
    }
  };

  const columns: ResponsiveColumn<Attachment>[] = [
    {
      id: 'name', sortKey: 'name', header: t('companyFilesPage.table.name'), mobileTitle: true,
      cell: (file) => (
        <span className="flex items-center gap-2 font-medium">
          <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{file.original_filename}</span>
        </span>
      ),
    },
    {
      id: 'deal', header: t('companyFilesPage.table.deal'),
      cell: (file) => (file.deal
        ? <DealLink dealId={file.deal} />
        : <span className="text-muted-foreground">—</span>),
    },
    {
      id: 'kind', header: t('companyFilesPage.table.kind'),
      cell: (file) => (file.kind
        ? <Badge variant={KIND_VARIANT[file.kind]}>{t(`companyFilesPage.kind.${file.kind}`)}</Badge>
        : <span className="text-muted-foreground">—</span>),
    },
    {
      id: 'uploadedBy', header: t('companyFilesPage.table.uploadedBy'), className: 'text-muted-foreground',
      cell: (file) => file.uploaded_by_email || '—',
    },
    {
      id: 'date', sortKey: 'uploaded_at', header: t('companyFilesPage.table.date'), className: 'text-xs text-muted-foreground',
      cell: (file) => formatDate(file.uploaded_at),
    },
    {
      id: 'actions', header: t('companyFilesPage.table.actions'), className: 'text-right', mobileActions: true,
      cell: (file) => (
        <Button
          variant="ghost"
          size="icon"
          aria-label={t('companyFilesPage.table.download')}
          onClick={() => onDownload(file)}
        >
          <Download className="h-4 w-4" />
        </Button>
      ),
    },
  ];

  return (
    <PageShell
      title={t('companyFilesPage.title')}
      description={t('companyFilesPage.description')}
      icon={<FolderOpen className="h-5 w-5" />}
      stats={stats}
      statsError={isError}
      actions={[{
        label: t('companyFilesPage.upload'),
        onClick: () => fileInputRef.current?.click(),
        // Viewer-mode admins can't act; without a company there's no valid parent.
        disabled: companyId == null || uploadFile.isPending,
      }]}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept={UPLOAD_ACCEPT}
        className="hidden"
        onChange={onUploadSelected}
      />
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('companyFilesPage.searchPlaceholder')}
        filters={[
          {
            key: 'kind',
            value: listParams.filters.kind,
            onChange: (v) => listParams.setFilter('kind', v),
            allLabel: t('companyFilesPage.allKinds'),
            options: KIND_CODES.map((k) => ({ value: k, label: t(`companyFilesPage.kind.${k}`) })),
          },
        ]}
      />
      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(attachments ?? [], listParams, {
              searchFields: (a) => [a.original_filename, a.uploaded_by_email],
              filterPredicates: { kind: (a, v) => a.kind === v },
              sortAccessors: {
                name: (a) => a.original_filename,
                uploaded_at: (a) => a.uploaded_at,
              },
            });
            if (isLoading) return <LoadingRows rows={6} />;
            if (isError) return <ErrorState onRetry={refetch} />;
            if (!pageItems.length) {
              // Files are attached inside a deal / заявка (or company/product) — never uploaded
              // here — so the empty state points there instead of implying a missing «upload» button.
              return <EmptyState icon={<FolderOpen className="h-5 w-5" />} message={t('companyFilesPage.emptyState')} />;
            }
            return (
              <>
                <ResponsiveDataTable
                  columns={columns}
                  rows={pageItems}
                  getRowId={(file) => file.id}
                  // Clicking the row downloads the file — consistent with the action column and the
                  // «registry row opens the document» pattern. Clicks on the DealLink / download
                  // button are excluded by the shared control guard.
                  onRowClick={onDownload}
                  sorting={{ ordering: listParams.ordering, onToggle: listParams.toggleOrdering }}
                />
                <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
              </>
            );
          })()}
        </CardContent>
      </Card>
    </PageShell>
  );
}

export default CompanyFilesPage;
