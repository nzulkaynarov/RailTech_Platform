import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { FolderOpen, Download, FileText } from 'lucide-react';
import { fetchDocumentBlob, saveBlob } from '@/lib/documents';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import {
  Toolbar, SortableHead, Pager, useListParams, applyListParams,
} from '@/components/DataTable';
import { useCompanyAttachments } from '@/hooks/useSourcing';
import { DealLink } from '@/components/Shared/DealLink';
import type { Attachment } from '@/api/sourcingApi';

type AttachmentKind = NonNullable<Attachment['kind']>;

const KIND_VARIANT: Record<AttachmentKind, 'default' | 'secondary'> = {
  SOURCE: 'secondary',
  SUPPORTING: 'default',
};
const KIND_CODES: AttachmentKind[] = ['SOURCE', 'SUPPORTING'];

export function CompanyFilesPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['kind'] as const, { defaultOrdering: '-uploaded_at' });
  const { data: attachments, isLoading, isError, refetch } = useCompanyAttachments();

  const stats = useMemo(() => {
    const list = attachments ?? [];
    return [
      { label: t('companyFilesPage.stats.total'), value: String(list.length) },
      { label: t('companyFilesPage.stats.sources'), value: String(list.filter((a) => a.kind === 'SOURCE').length) },
      { label: t('companyFilesPage.stats.documents'), value: String(list.filter((a) => a.kind === 'SUPPORTING').length) },
    ];
  }, [attachments, t]);

  const onDownload = async (file: Attachment) => {
    try {
      const blob = await fetchDocumentBlob(`sourcing/attachments/${file.id}/download/`);
      saveBlob(blob, file.original_filename || `RailTech_File_${file.id}`);
    } catch {
      toast.error(t('errors.operationFailed'));
    }
  };

  return (
    <PageShell
      title={t('companyFilesPage.title')}
      description={t('companyFilesPage.description')}
      icon={<FolderOpen className="h-5 w-5" />}
      stats={stats}
    >
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
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead sortKey="name" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('companyFilesPage.table.name')}
                      </SortableHead>
                      <TableHead>{t('companyFilesPage.table.deal')}</TableHead>
                      <TableHead>{t('companyFilesPage.table.kind')}</TableHead>
                      <TableHead>{t('companyFilesPage.table.uploadedBy')}</TableHead>
                      <SortableHead sortKey="uploaded_at" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('companyFilesPage.table.date')}
                      </SortableHead>
                      <TableHead className="text-right">{t('companyFilesPage.table.actions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pageItems.map((file) => (
                      <TableRow key={file.id}>
                        <TableCell className="flex items-center gap-2 font-medium">
                          <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                          <span className="truncate">{file.original_filename}</span>
                        </TableCell>
                        <TableCell>
                          {file.deal ? <DealLink dealId={file.deal} /> : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell>
                          {file.kind ? (
                            <Badge variant={KIND_VARIANT[file.kind]}>{t(`companyFilesPage.kind.${file.kind}`)}</Badge>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{file.uploaded_by_email || '—'}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {new Date(file.uploaded_at).toLocaleDateString()}
                        </TableCell>
                        <TableCell className="text-right" data-row-action>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={t('companyFilesPage.table.download')}
                            onClick={() => onDownload(file)}
                          >
                            <Download className="h-4 w-4" />
                          </Button>
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
    </PageShell>
  );
}

export default CompanyFilesPage;
