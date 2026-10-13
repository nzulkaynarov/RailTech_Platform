import { useTranslation } from 'react-i18next'; import { Package, Pencil, Trash2, Send } from 'lucide-react'; import { Card, CardContent } from '@/components/ui/card'; import { Badge } from '@/components/ui/badge'; import { Button } from '@/components/ui/button'; import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'; import { SortableHead, Pager } from '@/components/DataTable';
import { applyListParams, type useListParams } from '@/components/DataTable/listParams';
import { LoadingRows, EmptyState, ErrorState } from '../shared/PageShell';
import { productStatusLabelKey } from '@/lib/codes';
import { getDomainLabelKey } from '@/config/domainConfig';
import type { Product } from '@/api/catalogApi';

type ListParams = ReturnType<typeof useListParams>;

export function CatalogTable({
  products, isLoading, isError, refetch, listParams,
  onEdit, onPublish, onDelete,
}: {
  products: Product[] | undefined;
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
  listParams: ListParams;
  onEdit: (p: Product) => void;
  onPublish: (p: Product) => void;
  onDelete: (p: Product) => void;
}) {
  const { t } = useTranslation();

  // A product with a blank/DRAFT status is never PUBLISHED and has no other way to
  // go live — surface a quick publish affordance on those rows only.
  const canPublish = (p: Product) => p.status_code !== 'PUBLISHED';

  const { items: pageItems, total } = applyListParams(products ?? [], listParams, {
    searchFields: () => [],
    filterPredicates: {
      status: (p, v) => p.status_code === v,
    },
    sortAccessors: {
      sku: (p) => p.sku ?? '',
      name: (p) => p.name ?? '',
      domain: (p) => p.domain_type_name ?? '',
      status: (p) => p.status_name ?? '',
      manufacturer: (p) => p.brand_name ?? '',
    },
  });

  return (
    <Card>
      <CardContent className="p-0">
        {isLoading ? (
          <LoadingRows rows={6} />
        ) : isError ? (
          <ErrorState onRetry={() => refetch()} />
        ) : !pageItems.length ? (
          <EmptyState icon={<Package className="h-5 w-5" />} message={t('adminCatalog.emptyState')} />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead sortKey="sku" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCatalog.table.sku')}</SortableHead>
                  <SortableHead sortKey="name" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCatalog.table.name')}</SortableHead>
                  <SortableHead sortKey="domain" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCatalog.table.domain')}</SortableHead>
                  <SortableHead sortKey="status" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCatalog.table.status')}</SortableHead>
                  <SortableHead sortKey="manufacturer" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCatalog.table.manufacturer')}</SortableHead>
                  <TableHead className="text-right">{t('adminCatalog.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-mono text-xs">{p.sku ?? '—'}</TableCell>
                    <TableCell>{p.name}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {p.domain_type_code ? t(getDomainLabelKey(p.domain_type_code), p.domain_type_name) : '—'}
                    </TableCell>
                    <TableCell><Badge variant="outline">{productStatusLabelKey(p.status_code) ? t(productStatusLabelKey(p.status_code)) : (p.status_name || '—')}</Badge></TableCell>
                    <TableCell className="text-muted-foreground text-xs">{p.brand_name ?? '—'}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        {canPublish(p) && (
                          <Button variant="ghost" size="sm" onClick={() => onPublish(p)} title={t('adminCatalog.publish')}>
                            <Send className="h-3.5 w-3.5 text-primary" />
                          </Button>
                        )}
                        <Button variant="ghost" size="sm" onClick={() => onEdit(p)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => onDelete(p)}>
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pager page={listParams.page} pageSize={listParams.pageSize} total={total} onPageChange={listParams.setPage} />
          </>
        )}
      </CardContent>
    </Card>
  );
}
