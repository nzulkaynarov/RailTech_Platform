import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { translateApiError } from '@/lib/apiError';
import { ScrollText, Download, PenLine } from 'lucide-react';
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
import { useActs, useSignAct } from '@/hooks/useBilling';
import { useIsViewerMode } from '@/hooks/useViewerMode';
import { actsApi } from '@/api/billingApi';
import type { ActStatus } from '@/api/billingApi';

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

  return (
    <PageShell
      title={t('actsPage.title')}
      description={t('actsPage.description')}
      icon={<ScrollText className="h-5 w-5" />}
      stats={stats}
    >
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
                      <TableRow key={a.id}>
                        <TableCell className="font-medium">{a.number}</TableCell>
                        <TableCell>#{a.deal}</TableCell>
                        <TableCell className="tabular-nums">{a.total_amount}</TableCell>
                        <TableCell>
                          <Badge variant={STATUS_VARIANT[a.status]}>
                            {t(`actsPage.status.${a.status}`)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {a.issued_at ? new Date(a.issued_at).toLocaleDateString() : '—'}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-1">
                            {a.pdf_url && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={async () => {
                                  try {
                                    await actsApi.downloadPdf(a.id);
                                  } catch (e) {
                                    toast.error(translateApiError(e));
                                  }
                                }}
                              >
                                <Download className="h-4 w-4" />
                              </Button>
                            )}
                            {a.status === 'ISSUED' && (
                              <label
                                className={`inline-flex items-center rounded-md px-2 py-1 text-xs ${isViewer ? 'cursor-not-allowed opacity-60' : 'cursor-pointer hover:bg-accent'}`}
                                title={isViewer ? viewerTip : undefined}
                              >
                                <PenLine className="h-4 w-4" />
                                <input
                                  type="file"
                                  className="hidden"
                                  accept=".pdf,.jpg,.png"
                                  disabled={isViewer}
                                  onChange={(e) => {
                                    const f = e.target.files?.[0];
                                    onSign(a.id, f);
                                  }}
                                />
                              </label>
                            )}
                          </div>
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

export default ActsPage;
