import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { extractBlobErrorCode, fetchDocumentBlob, saveBlob } from '@/lib/documents';
import { ScrollText, PenLine, Download } from 'lucide-react';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { ManualModeBanner } from '@/components/Shared/ManualModeBanner';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
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
import { useActs, useSignAct } from '@/hooks/useBilling';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { useCurrencyStore } from '@/store/currencyStore';
import { openableRowProps } from '@/lib/rowClick';
import { DealLink } from '@/components/Shared/DealLink';
import type { Act, ActStatus } from '@/api/billingApi';

const STATUS_VARIANT: Record<ActStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  DRAFT: 'secondary',
  ISSUED: 'outline',
  SIGNED: 'default',
  CANCELLED: 'destructive',
};
const STATUS_CODES: ActStatus[] = ['DRAFT', 'ISSUED', 'SIGNED', 'CANCELLED'];

export function ActsPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['status'] as const, { defaultOrdering: '-created_at' });
  const { data: acts, isLoading, isError, refetch } = useActs(undefined);
  const signAct = useSignAct();
  const isViewer = useIsViewerMode();
  const viewerTip = t('apiErrors.ADMIN_VIEWER_CANNOT_ACT');
  const formatCurrency = useCurrencyStore((s) => s.format);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = useMemo(() => (acts ?? []).find((a) => a.id === selectedId) ?? null, [acts, selectedId]);

  const stats = useMemo(() => {
    const list = acts ?? [];
    return [
      { label: t('actsPage.stats.total'), value: String(list.length) },
      { label: t('actsPage.stats.issued'), value: String(list.filter((a) => a.status === 'ISSUED').length) },
      { label: t('actsPage.stats.signed'), value: String(list.filter((a) => a.status === 'SIGNED').length) },
    ];
  }, [acts, t]);

  const onSign = async (id: number, file?: File) => {
    try {
      await signAct.mutateAsync({ id, signedFile: file });
      toast.success(t('actsPage.signed'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const onDownloadSigned = async (act: Act) => {
    try {
      const blob = await fetchDocumentBlob(`crm/acts/${act.id}/download-signed/`);
      const ext = blob.type.includes('pdf') ? 'pdf' : (blob.type.split('/')[1] || 'bin');
      saveBlob(blob, `RailTech_Act_${act.id}_signed.${ext}`);
    } catch (err) {
      // Surface the real backend code (403/404/expiry) instead of a generic message. Blob-response
      // error bodies aren't plain JSON — parse the code out first, fall back to the generic string.
      const code = await extractBlobErrorCode(err);
      toast.error(code ? translateApiError(code) : t('errors.operationFailed'));
    }
  };

  return (
    <PageShell
      title={t('actsPage.title')}
      description={t('actsPage.description')}
      icon={<ScrollText className="h-5 w-5" />}
      stats={stats}
    >
      <ManualModeBanner kind="esign" />
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('actsPage.table.number')}
        filters={[
          {
            key: 'status',
            value: listParams.filters.status,
            onChange: (v) => listParams.setFilter('status', v),
            allLabel: t('actsPage.allStatuses'),
            options: STATUS_CODES.map((s) => ({ value: s, label: t(`actsPage.status.${s}`) })),
          },
        ]}
      />
      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(acts ?? [], listParams, {
              searchFields: (a) => [a.number, String(a.deal)],
              filterPredicates: { status: (a, v) => a.status === v },
              sortAccessors: {
                number: (a) => a.number,
                total: (a) => Number(a.total_amount),
                issued: (a) => a.issued_at ?? '',
                created_at: (a) => a.created_at,
              },
            });
            if (isLoading) return <LoadingRows rows={6} />;
            if (isError) return <ErrorState onRetry={refetch} />;
            if (!pageItems.length) {
              // Acts are generated from an invoice — never created directly — so the empty state
              // explains where they come from instead of implying a missing «create» button.
              return <EmptyState icon={<ScrollText className="h-5 w-5" />} message={t('actsPage.emptyState')} />;
            }
            return (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableHead sortKey="number" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('actsPage.table.number')}
                      </SortableHead>
                      <TableHead>{t('actsPage.table.deal')}</TableHead>
                      <SortableHead sortKey="total" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('actsPage.table.total')}
                      </SortableHead>
                      <TableHead>{t('actsPage.table.status')}</TableHead>
                      <SortableHead sortKey="issued" current={listParams.ordering} onChange={listParams.toggleOrdering}>
                        {t('actsPage.table.issued')}
                      </SortableHead>
                      <TableHead className="text-right">{t('actsPage.table.actions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pageItems.map((a) => (
                      <TableRow key={a.id} {...openableRowProps(() => setSelectedId(a.id), `${t('common.open')} ${a.number}`)}>
                        <TableCell className="font-medium">{a.number}</TableCell>
                        <TableCell><DealLink dealId={a.deal} /></TableCell>
                        <TableCell className="tabular-nums">{formatCurrency(Number(a.total_amount))}</TableCell>
                        <TableCell>
                          <Badge variant={STATUS_VARIANT[a.status]}>
                            {t(`actsPage.status.${a.status}`)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {a.issued_at ? new Date(a.issued_at).toLocaleDateString() : '—'}
                        </TableCell>
                        <TableCell className="text-right" data-row-action>
                          {a.pdf_url && (
                            <DocumentActions
                              request={() => ({ path: `crm/acts/${a.id}/download-pdf/` })}
                              filenameBase={`RailTech_Act_${a.id}`}
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

      {selected && (
        <Sheet open={!!selected} onOpenChange={(o) => !o && setSelectedId(null)}>
          <SheetContent className="overflow-y-auto sm:max-w-lg">
            <SheetHeader>
              <SheetTitle>{selected.number}</SheetTitle>
              <SheetDescription>
                <Badge variant={STATUS_VARIANT[selected.status]}>{t(`actsPage.status.${selected.status}`)}</Badge>
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-4 p-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><Label>{t('actsPage.table.deal')}</Label><DealLink dealId={selected.deal} /></div>
                <div><Label>{t('actsPage.table.total')}</Label><p className="tabular-nums">{formatCurrency(Number(selected.total_amount))}</p></div>
                <div><Label>{t('actsPage.table.issued')}</Label><p className="text-muted-foreground">{selected.issued_at ? new Date(selected.issued_at).toLocaleDateString() : '—'}</p></div>
                <div><Label>{t('actsPage.signedAt')}</Label><p className="text-muted-foreground">{selected.signed_at ? new Date(selected.signed_at).toLocaleString() : '—'}</p></div>
              </div>
              <div className="flex flex-col gap-2">
                {selected.pdf_url && (
                  <DocumentActions
                    request={() => ({ path: `crm/acts/${selected.id}/download-pdf/` })}
                    filenameBase={`RailTech_Act_${selected.id}`}
                    size="default"
                  />
                )}
                {selected.signed_file_url && (
                  <Button variant="outline" onClick={() => onDownloadSigned(selected)}>
                    <Download className="mr-2 h-4 w-4" />
                    {t('actsPage.downloadSigned')}
                  </Button>
                )}
                {selected.status === 'ISSUED' && (
                  <label
                    className={`flex items-center justify-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-sm ${isViewer ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:bg-accent'}`}
                    title={isViewer ? viewerTip : undefined}
                  >
                    <PenLine className="h-4 w-4" />
                    <span>{t('actsPage.uploadSigned')}</span>
                    <input
                      type="file"
                      className="hidden"
                      accept=".pdf,.jpg,.jpeg,.png"
                      disabled={isViewer}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) onSign(selected.id, f);
                      }}
                    />
                  </label>
                )}
              </div>
            </div>
            <SheetFooter />
          </SheetContent>
        </Sheet>
      )}
    </PageShell>
  );
}

export default ActsPage;
