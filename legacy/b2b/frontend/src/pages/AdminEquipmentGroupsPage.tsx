import { useState } from 'react'; import { useDraftState } from '@/hooks/useDraftState'; import { useTranslation } from 'react-i18next'; import { toast } from 'sonner'; import { Factory, Pencil, Trash2 } from 'lucide-react'; import { Card, CardContent } from '@/components/ui/card'; import { Button } from '@/components/ui/button'; import { Input } from '@/components/ui/input'; import { Textarea } from '@/components/ui/textarea'; import { Label } from '@/components/ui/label'; import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'; import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'; import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet'; import { Toolbar, SortableHead, Pager } from '@/components/DataTable';
import { useListParams, applyListParams } from '@/components/DataTable/listParams';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import {
  useEquipmentGroups, useCreateEquipmentGroup, useUpdateEquipmentGroup, useDeleteEquipmentGroup,
} from '@/hooks/useCatalog';
import type { EquipmentGroup } from '@/api/catalogApi';

type Draft = Partial<EquipmentGroup>;

function GroupFormSheet({
  open, onOpenChange, target, all,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  target: EquipmentGroup | null;
  all: EquipmentGroup[];
}) {
  const { t } = useTranslation();
  const createMut = useCreateEquipmentGroup();
  const updateMut = useUpdateEquipmentGroup();
  const [draft, setDraft] = useDraftState<EquipmentGroup | null, Draft>(target, (t) => t ?? { name: '' });


  const busy = createMut.isPending || updateMut.isPending;
  const isEdit = Boolean(target?.id);
  const update = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const submit = async () => {
    if (!draft.name?.trim()) {
      toast.error(t('adminEquipmentGroups.nameRequired'));
      return;
    }
    const payload: Partial<EquipmentGroup> = {
      name: draft.name,
      parent: draft.parent ? Number(draft.parent) : null,
      description: draft.description ?? '',
      sort_order: draft.sort_order ?? 0,
      is_active: draft.is_active ?? true,
    };
    try {
      if (isEdit && target) {
        await updateMut.mutateAsync({ id: target.id, data: payload });
        toast.success(t('adminEquipmentGroups.updated'));
      } else {
        await createMut.mutateAsync(payload);
        toast.success(t('adminEquipmentGroups.created'));
      }
      onOpenChange(false);
    } catch {
      toast.error(t('adminEquipmentGroups.saveFailed'));
    }
  };

  const parentOptions = all.filter((g) => g.id !== target?.id);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{isEdit ? t('adminEquipmentGroups.edit') : t('adminEquipmentGroups.new')}</SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-4 px-4">
          <div className="space-y-2">
            <Label>{t('adminEquipmentGroups.fields.name')}</Label>
            <Input value={draft.name ?? ''} onChange={(e) => update({ name: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label>{t('adminEquipmentGroups.fields.parent')}</Label>
            <Select
              value={draft.parent ? String(draft.parent) : undefined}
              onValueChange={(v) => update({ parent: Number(v) })}
            >
              <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
              <SelectContent>
                {parentOptions.map((g) => (
                  <SelectItem key={g.id} value={String(g.id)}>{g.full_path || g.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>{t('adminEquipmentGroups.fields.description')}</Label>
            <Textarea rows={2} value={draft.description ?? ''} onChange={(e) => update({ description: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label>{t('adminEquipmentGroups.fields.sortOrder')}</Label>
            <Input
              type="number"
              value={draft.sort_order ?? 0}
              onChange={(e) => update({ sort_order: Number(e.target.value) })}
            />
          </div>
        </div>

        <SheetFooter className="mt-6">
          <Button onClick={submit} disabled={busy} className="w-full">
            {isEdit ? t('adminEquipmentGroups.save') : t('adminEquipmentGroups.create')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export function AdminEquipmentGroupsPage() {
  const { t } = useTranslation();
  // Fetch every group (DRF pages at 20) so search/sort/Pager + stat tiles see all rows (H4).
  const { data: groups, isLoading, isError, refetch } = useEquipmentGroups(undefined, { fetchAll: true });
  const deleteMut = useDeleteEquipmentGroup();

  const listParams = useListParams([], { defaultOrdering: 'path' });
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EquipmentGroup | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<EquipmentGroup | null>(null);

  const onEdit = (g: EquipmentGroup) => {
    setEditTarget(g);
    setSheetOpen(true);
  };
  const onNew = () => {
    setEditTarget(null);
    setSheetOpen(true);
  };
  const onDelete = async () => {
    if (!deleteTarget) return;
    await deleteMut.mutateAsync(deleteTarget.id);
    toast.success(t('adminEquipmentGroups.deleted'));
  };

  const stats = [
    { label: t('adminEquipmentGroups.stats.total'), value: String(groups?.length ?? '—') },
    { label: t('adminEquipmentGroups.stats.roots'), value: String(groups?.filter((g) => !g.parent).length ?? '—') },
  ];

  return (
    <PageShell
      title={t('adminEquipmentGroups.title')}
      description={t('adminEquipmentGroups.description')}
      icon={<Factory className="h-5 w-5" />}
      stats={stats}
      statsError={isError}
    >
      <Toolbar
        searchValue={listParams.searchInput}
        onSearchChange={listParams.setSearchInput}
        newLabel={t('adminEquipmentGroups.new')}
        onNew={onNew}
      />

      <Card>
        <CardContent className="p-0">
          {(() => {
            const { items: pageItems, total } = applyListParams(groups ?? [], listParams, {
              searchFields: (g) => [g.full_path, g.name],
              sortAccessors: {
                path: (g) => g.full_path || g.name,
              },
            });
            if (isLoading) return <LoadingRows rows={5} />;
            if (isError) return <ErrorState onRetry={() => refetch()} />;
            if (!pageItems.length) return <EmptyState icon={<Factory className="h-5 w-5" />} message={t('adminEquipmentGroups.emptyState')} />;
            return (
            <>
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHead sortKey="path" current={listParams.ordering} onChange={listParams.toggleOrdering}>{t('adminEquipmentGroups.table.path')}</SortableHead>
                  <TableHead className="text-right">{t('adminEquipmentGroups.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageItems.map((g) => (
                  <TableRow key={g.id}>
                    <TableCell className="text-sm">{g.full_path || g.name}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => onEdit(g)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(g)}>
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

      <GroupFormSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        target={editTarget}
        all={groups ?? []}
      />

      <ConfirmActionDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title={t('adminEquipmentGroups.confirmDelete')}
        description={t('adminEquipmentGroups.confirmDeleteDesc', { name: deleteTarget?.full_path || deleteTarget?.name })}
        variant="destructive"
        confirmLabel={t('adminEquipmentGroups.delete')}
        cancelLabel={t('adminEquipmentGroups.cancel')}
        onConfirm={onDelete}
      />
    </PageShell>
  );
}

export default AdminEquipmentGroupsPage;
