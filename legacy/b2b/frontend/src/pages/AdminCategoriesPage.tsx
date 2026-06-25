import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Layers, Pencil, Trash2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet';
import { Toolbar, SortableHead, Pager, useListParams, applyListParams } from '@/components/DataTable';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import {
  useCategories, useCreateCategory, useUpdateCategory, useDeleteCategory, useDomainTypes,
} from '@/hooks/useCatalog';
import type { Category } from '@/api/catalogApi';

type Draft = Partial<Category>;

function CategoryFormSheet({
  open, onOpenChange, target, all,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  target: Category | null;
  all: Category[];
}) {
  const { t } = useTranslation();
  const { data: domainTypes } = useDomainTypes();
  const createMut = useCreateCategory();
  const updateMut = useUpdateCategory();

  const [draft, setDraft] = useState<Draft>(() => target ?? { name: '' });
  useMemo(() => setDraft(target ?? { name: '' }), [target]);

  const busy = createMut.isPending || updateMut.isPending;
  const isEdit = Boolean(target?.id);

  const update = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const submit = async () => {
    if (!draft.name?.trim()) {
      toast.error(t('adminCategories.nameRequired'));
      return;
    }
    const payload: Partial<Category> = {
      name: draft.name,
      parent: draft.parent ? Number(draft.parent) : null,
      domain_type: draft.domain_type ? Number(draft.domain_type) : null,
      sort_order: draft.sort_order ?? 0,
      is_active: draft.is_active ?? true,
    };
    try {
      if (isEdit && target) {
        await updateMut.mutateAsync({ id: target.id, data: payload });
        toast.success(t('adminCategories.updated'));
      } else {
        await createMut.mutateAsync(payload);
        toast.success(t('adminCategories.created'));
      }
      onOpenChange(false);
    } catch {
      toast.error(t('adminCategories.saveFailed'));
    }
  };

  const parentOptions = all.filter((c) => c.id !== target?.id);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{isEdit ? t('adminCategories.edit') : t('adminCategories.new')}</SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-4 px-4">
          <div className="space-y-2">
            <Label>{t('adminCategories.fields.name')}</Label>
            <Input value={draft.name ?? ''} onChange={(e) => update({ name: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label>{t('adminCategories.fields.domainType')}</Label>
            <Select
              value={draft.domain_type ? String(draft.domain_type) : undefined}
              onValueChange={(v) => update({ domain_type: Number(v) })}
            >
              <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
              <SelectContent>
                {(domainTypes ?? []).map((d) => (
                  <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>{t('adminCategories.fields.parent')}</Label>
            <Select
              value={draft.parent ? String(draft.parent) : undefined}
              onValueChange={(v) => update({ parent: Number(v) })}
            >
              <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
              <SelectContent>
                {parentOptions.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>{t('adminCategories.fields.sortOrder')}</Label>
            <Input
              type="number"
              value={draft.sort_order ?? 0}
              onChange={(e) => update({ sort_order: Number(e.target.value) })}
            />
          </div>
        </div>

        <SheetFooter className="mt-6">
          <Button onClick={submit} disabled={busy} className="w-full">
            {isEdit ? t('adminCategories.save') : t('adminCategories.create')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export function AdminCategoriesPage() {
  const { t } = useTranslation();
  // Fetch every category (DRF pages at 20) so search/sort/Pager + stat tiles see all rows (H4).
  const { data: categories, isLoading } = useCategories({ fetchAll: true });
  const deleteMut = useDeleteCategory();

  const listParams = useListParams([], { defaultOrdering: 'sort_order' });
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Category | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Category | null>(null);

  const nameById = useMemo(() => {
    const categoryMap = new Map<number, string>();
    (categories ?? []).forEach((c) => categoryMap.set(c.id, c.name));
    return categoryMap;
  }, [categories]);

  const onEdit = (c: Category) => {
    setEditTarget(c);
    setSheetOpen(true);
  };
  const onNew = () => {
    setEditTarget(null);
    setSheetOpen(true);
  };
  const onDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMut.mutateAsync(deleteTarget.id);
      toast.success(t('adminCategories.deleted'));
      setDeleteTarget(null);
    } catch {
      toast.error(t('adminCategories.deleteFailed'));
    }
  };

  const stats = [
    { label: t('adminCategories.stats.total'), value: String(categories?.length ?? '—') },
    { label: t('adminCategories.stats.roots'), value: String(categories?.filter((c) => !c.parent).length ?? '—') },
  ];

  return (
    <PageShell
      title={t('adminCategories.title')}
      description={t('adminCategories.description')}
      icon={<Layers className="h-5 w-5" />}
      stats={stats}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        newLabel={t('adminCategories.new')}
        onNew={onNew}
      />

      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(categories ?? [], listParams, {
              searchFields: (c) => [c.name],
              sortAccessors: {
                name: (c) => c.name,
                sort_order: (c) => c.sort_order ?? 0,
              },
            });
            if (isLoading) return <LoadingRows rows={5} />;
            if (!pageItems.length) return <EmptyState icon={<Layers className="h-5 w-5" />} message={t('adminCategories.emptyState')} />;
            return (
            <>
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead sortKey="name" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCategories.table.name')}</SortableHead>
                  <SortableHead sortKey="" current="" onChange={() => {}}>{t('adminCategories.table.parent')}</SortableHead>
                  <SortableHead sortKey="sort_order" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminCategories.table.order')}</SortableHead>
                  <SortableHead sortKey="" current="" onChange={() => {}} className="text-right">{t('adminCategories.table.actions')}</SortableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>{c.name}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {c.parent ? nameById.get(c.parent) ?? c.parent : '—'}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">{c.sort_order ?? 0}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => onEdit(c)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(c)}>
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
            );
          })()}
        </CardContent>
      </Card>

      <CategoryFormSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        target={editTarget}
        all={categories ?? []}
      />

      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('adminCategories.confirmDelete')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('adminCategories.confirmDeleteDesc', { name: deleteTarget?.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('adminCategories.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete} disabled={deleteMut.isPending}>
              {t('adminCategories.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}

export default AdminCategoriesPage;
