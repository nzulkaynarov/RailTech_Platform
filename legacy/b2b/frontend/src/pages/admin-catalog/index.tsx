import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getDomainLabelKey } from '@/config/domainConfig';
import { toast } from 'sonner';
import { Package } from 'lucide-react';
import { Toolbar, useListParams } from '@/components/DataTable';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { PageShell } from '../shared/PageShell';
import {
  useProducts, useDomainTypes, useProductStatuses,
  useDeleteProduct, useBulkPublishProducts,
} from '@/hooks/useCatalog';
import { productStatusLabelKey } from '@/lib/codes';
import type { Product } from '@/api/catalogApi';
import { ProductFormSheet } from './ProductFormSheet';
import { CatalogTable } from './CatalogTable';

export function AdminCatalogPage() {
  const { t } = useTranslation();
  const listParams = useListParams(['domain', 'status'] as const, { defaultOrdering: 'name' });
  const { data: products, isLoading, isError, refetch } = useProducts({
    search: listParams.search || undefined,
    domain_type: listParams.filters.domain === 'all' ? undefined : listParams.filters.domain,
    // Fetch the complete set so client-side search/sort/Pager + stat tiles are accurate
    // (DRF caps each page at 20; H4). Server already filters by search/domain.
    fetchAll: true,
  });
  const { data: domainTypes } = useDomainTypes();
  const { data: statuses } = useProductStatuses();
  const deleteMut = useDeleteProduct();
  const publishMut = useBulkPublishProducts();

  const [sheetOpen, setSheetOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Product | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Product | null>(null);
  const [publishTarget, setPublishTarget] = useState<Product | null>(null);

  const onEdit = (p: Product) => {
    setEditTarget(p);
    setSheetOpen(true);
  };
  const onNew = () => {
    setEditTarget(null);
    setSheetOpen(true);
  };

  const onDelete = async () => {
    if (!deleteTarget) return;
    await deleteMut.mutateAsync(deleteTarget.id);
    toast.success(t('adminCatalog.deleted'));
  };

  const onPublish = async () => {
    if (!publishTarget) return;
    await publishMut.mutateAsync([publishTarget.id]);
    toast.success(t('adminCatalog.published'));
  };

  const stats = [
    { label: t('adminCatalog.stats.total'), value: String(products?.length ?? '—') },
    {
      label: t('adminCatalog.stats.published'),
      value: String(products?.filter((p) => p.status_code === 'PUBLISHED').length ?? '—'),
    },
    {
      label: t('adminCatalog.stats.draft'),
      value: String(products?.filter((p) => p.status_code === 'DRAFT').length ?? '—'),
    },
  ];

  return (
    <PageShell
      title={t('adminCatalog.title')}
      description={t('adminCatalog.description')}
      icon={<Package className="h-5 w-5" />}
      stats={stats}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        searchPlaceholder={t('adminCatalog.searchPlaceholder')}
        filters={[
          {
            key: 'domain',
            value: listParams.filters.domain,
            onChange: (v) => listParams.setFilter('domain', v),
            allLabel: t('adminCatalog.allDomains'),
            // Localize by CODE like the status filter below; `d.name` is the i18next
            // defaultValue, used only when the domain code has no configured key.
            options: (domainTypes ?? []).map((d) => ({
              value: d.code,
              label: t(getDomainLabelKey(d.code), d.name),
            })),
          },
          {
            key: 'status',
            value: listParams.filters.status,
            onChange: (v) => listParams.setFilter('status', v),
            allLabel: t('adminCatalog.allStatuses'),
            options: (statuses ?? []).map((s) => ({
              value: s.code,
              label: productStatusLabelKey(s.code) ? t(productStatusLabelKey(s.code)) : s.name,
            })),
          },
        ]}
        newLabel={t('adminCatalog.newProduct')}
        onNew={onNew}
      />

      <CatalogTable
        products={products}
        isLoading={isLoading}
        isError={isError}
        refetch={refetch}
        listParams={listParams}
        onEdit={onEdit}
        onPublish={(p) => setPublishTarget(p)}
        onDelete={(p) => setDeleteTarget(p)}
      />

      <ProductFormSheet open={sheetOpen} onOpenChange={setSheetOpen} target={editTarget} />

      <ConfirmActionDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={t('adminCatalog.confirmDelete')}
        description={t('adminCatalog.confirmDeleteDesc', { name: deleteTarget?.name })}
        variant="destructive"
        confirmLabel={t('adminCatalog.delete')}
        cancelLabel={t('adminCatalog.cancel')}
        onConfirm={onDelete}
      />

      <ConfirmActionDialog
        open={!!publishTarget}
        onOpenChange={(o) => !o && setPublishTarget(null)}
        title={t('adminCatalog.confirmPublish')}
        description={t('adminCatalog.confirmPublishDesc', { name: publishTarget?.name })}
        variant="primary"
        confirmLabel={t('adminCatalog.publish')}
        cancelLabel={t('adminCatalog.cancel')}
        onConfirm={onPublish}
      />
    </PageShell>
  );
}

export { ProductFormSheet } from './ProductFormSheet';

export default AdminCatalogPage;
