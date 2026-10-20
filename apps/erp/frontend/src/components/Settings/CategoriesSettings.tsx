import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Layers, Plus, Pencil, Trash2, Loader2 } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';

import { useDraftState } from '@/hooks/useDraftState';
import {
  useCategories,
  useCreateCategory,
  useUpdateCategory,
  useDeleteCategory,
  useDomainTypes,
} from '@/hooks/useCatalog';
import type { Category } from '@/api/catalogApi';
import { translateApiError } from '@/lib/apiError';

type CategoryDraft = {
  name: string;
  parent?: number | null;
  domain_type?: number | null;
  sort_order?: number;
  is_active?: boolean;
};

const EMPTY_DRAFT: CategoryDraft = {
  name: '',
  parent: null,
  domain_type: null,
  sort_order: 0,
  is_active: true,
};

function CategoryDialog({
  open,
  onOpenChange,
  target,
  allCategories,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  target: Category | null;
  allCategories: Category[];
}) {
  const { t } = useTranslation();
  const { data: domainTypes } = useDomainTypes();
  const createMut = useCreateCategory();
  const updateMut = useUpdateCategory();

  const [draft, setDraft] = useDraftState<Category | null, CategoryDraft>(
    target,
    (cat) =>
      cat
        ? {
            name: cat.name ?? '',
            parent: cat.parent ? Number(cat.parent) : null,
            domain_type: cat.domain_type ? Number(cat.domain_type) : null,
            sort_order: cat.sort_order ?? 0,
            is_active: cat.is_active ?? true,
          }
        : EMPTY_DRAFT,
  );

  const busy = createMut.isPending || updateMut.isPending;
  const isEdit = Boolean(target?.id);

  const submit = async () => {
    if (!draft.name?.trim()) {
      toast.error(t('settings.categories.nameRequired'));
      return;
    }
    const payload = {
      name: draft.name.trim(),
      parent: draft.parent ? Number(draft.parent) : null,
      domain_type: draft.domain_type ? Number(draft.domain_type) : null,
      sort_order: draft.sort_order ?? 0,
      is_active: draft.is_active ?? true,
    };
    try {
      if (isEdit && target) {
        await updateMut.mutateAsync({ id: target.id, data: payload });
        toast.success(t('settings.categories.updated'));
      } else {
        await createMut.mutateAsync(payload);
        toast.success(t('settings.categories.created'));
      }
      onOpenChange(false);
    } catch (e) {
      toast.error(translateApiError(e) || t('settings.categories.saveFailed'));
    }
  };

  const parentOptions = allCategories.filter((c) => c.id !== target?.id);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t('settings.categories.editTitle') : t('settings.categories.createTitle')}
          </DialogTitle>
          <DialogDescription>
            {isEdit ? t('settings.categories.editDesc') : t('settings.categories.createDesc')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="cat-name">{t('settings.categories.name')}</Label>
            <Input
              id="cat-name"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder={t('settings.categories.namePlaceholder')}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="cat-domain">{t('settings.categories.domainType')}</Label>
            <Select
              value={draft.domain_type ? String(draft.domain_type) : '__none__'}
              onValueChange={(v) => setDraft({ ...draft, domain_type: v === '__none__' ? null : Number(v) })}
            >
              <SelectTrigger id="cat-domain">
                <SelectValue placeholder="—" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">— {t('settings.categories.noDomain')} —</SelectItem>
                {(domainTypes ?? []).map((d) => (
                  <SelectItem key={d.id} value={String(d.id)}>
                    {d.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="cat-parent">{t('settings.categories.parent')}</Label>
            <Select
              value={draft.parent ? String(draft.parent) : '__none__'}
              onValueChange={(v) => setDraft({ ...draft, parent: v === '__none__' ? null : Number(v) })}
            >
              <SelectTrigger id="cat-parent">
                <SelectValue placeholder="—" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">— {t('settings.categories.noParent')} —</SelectItem>
                {parentOptions.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="cat-sort">{t('settings.categories.sortOrder')}</Label>
            <Input
              id="cat-sort"
              type="number"
              value={draft.sort_order ?? 0}
              onChange={(e) => setDraft({ ...draft, sort_order: Number(e.target.value) })}
            />
          </div>

          <div className="flex items-center gap-2 pt-2">
            <Switch
              id="cat-active"
              checked={draft.is_active ?? true}
              onCheckedChange={(v) => setDraft({ ...draft, is_active: v })}
            />
            <Label htmlFor="cat-active" className="text-sm font-medium cursor-pointer">
              {t('common.active')}
            </Label>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} disabled={busy}>
            {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {isEdit ? t('common.save') : t('common.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function CategoriesSettings() {
  const { t } = useTranslation();
  const { data: categories, isLoading, isError, refetch } = useCategories({ fetchAll: true });
  const { data: domainTypes } = useDomainTypes();
  const deleteMut = useDeleteCategory();

  const [search, setSearch] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Category | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Category | null>(null);

  const domainNameById = useMemo(() => {
    const map = new Map<number, string>();
    (domainTypes ?? []).forEach((d) => map.set(d.id, d.name));
    return map;
  }, [domainTypes]);

  const categoryNameById = useMemo(() => {
    const map = new Map<number, string>();
    (categories ?? []).forEach((c) => map.set(c.id, c.name));
    return map;
  }, [categories]);

  // Подкатегории выбранной категории: с ними удалить нельзя (бэкенд — 400 CATEGORY_HAS_CHILDREN, FIX-42).
  const deleteTargetChildren = useMemo(
    () => (deleteTarget ? (categories ?? []).filter((c) => Number(c.parent) === deleteTarget.id) : []),
    [categories, deleteTarget],
  );

  const onEdit = (c: Category) => {
    setEditTarget(c);
    setDialogOpen(true);
  };

  const onNew = () => {
    setEditTarget(null);
    setDialogOpen(true);
  };

  const onDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMut.mutateAsync(deleteTarget.id);
      toast.success(t('settings.categories.deleted'));
      setDeleteTarget(null);
    } catch (e) {
      toast.error(translateApiError(e) || t('settings.categories.deleteFailed'));
    }
  };

  const filteredCategories = useMemo(() => {
    const list = categories ?? [];
    if (!search.trim()) return list;
    const q = search.trim().toLowerCase();
    return list.filter((c) => c.name.toLowerCase().includes(q));
  }, [categories, search]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <Layers className="h-5 w-5 text-primary" />
          {t('settings.categories.title')}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">{t('settings.categories.subtitle')}</p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('settings.categories.filterPlaceholder')}
          className="max-w-xs"
          aria-label={t('settings.categories.filterPlaceholder')}
        />
        <Button onClick={onNew} className="gap-2 ml-auto">
          <Plus className="h-4 w-4" />
          {t('settings.categories.new')}
        </Button>
      </div>

      {!isError && !isLoading && (
        <p className="text-xs text-muted-foreground" role="status">
          {t('settings.categories.shownCount', { count: filteredCategories.length })}
        </p>
      )}

      {isError ? (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
          <p className="text-sm text-destructive">{t('common.loadError')}</p>
          <Button variant="outline" className="mt-3" onClick={() => refetch()}>
            {t('common.retry')}
          </Button>
        </div>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('settings.categories.name')}</TableHead>
                  <TableHead>{t('settings.categories.parent')}</TableHead>
                  <TableHead>{t('settings.categories.domainType')}</TableHead>
                  <TableHead className="w-24 text-right">{t('settings.categories.sortOrder')}</TableHead>
                  <TableHead className="w-28">{t('settings.categories.status')}</TableHead>
                  <TableHead className="w-24 text-right">{t('common.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-8">
                      <Loader2 className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ) : filteredCategories.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center py-8 text-muted-foreground">
                      {t('settings.categories.empty')}
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredCategories.map((c) => {
                    const isActive = c.is_active !== false;
                    const parentName = c.parent ? categoryNameById.get(Number(c.parent)) : '—';
                    const domainName = c.domain_type ? domainNameById.get(Number(c.domain_type)) : '—';
                    return (
                      <TableRow key={c.id} className={!isActive ? 'opacity-60 bg-muted/20' : undefined}>
                        <TableCell className="font-medium">{c.name}</TableCell>
                        <TableCell>{parentName ?? '—'}</TableCell>
                        <TableCell>{domainName ?? '—'}</TableCell>
                        <TableCell className="text-right font-mono">{c.sort_order ?? 0}</TableCell>
                        <TableCell>
                          <Badge variant={isActive ? 'default' : 'secondary'} className="text-xs">
                            {isActive ? t('common.active') : t('common.inactive')}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => onEdit(c)}>
                              <Pencil className="h-4 w-4" />
                              <span className="sr-only">{t('common.edit')}</span>
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-destructive hover:bg-destructive/10"
                              onClick={() => setDeleteTarget(c)}
                            >
                              <Trash2 className="h-4 w-4" />
                              <span className="sr-only">{t('common.delete')}</span>
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <CategoryDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        target={editTarget}
        allCategories={categories ?? []}
      />

      <AlertDialog open={Boolean(deleteTarget)} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('settings.categories.confirmDeleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteTargetChildren.length > 0
                ? t('settings.categories.confirmDeleteHasChildren', {
                    names: deleteTargetChildren.map((c) => c.name).join(', '),
                  })
                : t('settings.categories.confirmDeleteDesc', { name: deleteTarget?.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={onDelete}
              disabled={deleteMut.isPending || deleteTargetChildren.length > 0}
            >
              {t('common.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default CategoriesSettings;
