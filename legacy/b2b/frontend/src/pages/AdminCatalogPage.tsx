import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Package, Search, Plus, Pencil, Trash2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';
import {
  useProducts, useCreateProduct, useUpdateProduct, useDeleteProduct,
  useDomainTypes, useProductStatuses, useCategories, useManufacturers,
} from '@/hooks/useCatalog';
import { useUnits } from '@/hooks/useMasterData';
import type { Product } from '@/api/catalogApi';

type Draft = Partial<Product> & { gost_drawing?: string | null; description?: string };

function emptyDraft(): Draft {
  return { name: '', description: '', gost_drawing: '' };
}

function ProductFormSheet({
  open, onOpenChange, target,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  target: Product | null;
}) {
  const { t } = useTranslation();
  const { data: domainTypes } = useDomainTypes();
  const { data: statuses } = useProductStatuses();
  const { data: categories } = useCategories();
  const { data: units } = useUnits();
  const { data: manufacturers } = useManufacturers();
  const createMut = useCreateProduct();
  const updateMut = useUpdateProduct();

  const [draft, setDraft] = useState<Draft>(() => target ?? emptyDraft());

  useMemo(() => {
    setDraft(target ? { ...target } : emptyDraft());
  }, [target]);

  const busy = createMut.isPending || updateMut.isPending;
  const isEdit = Boolean(target?.id);

  const update = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const submit = async () => {
    if (!draft.name?.trim()) {
      toast.error(t('adminCatalog.nameRequired'));
      return;
    }
    const payload: Partial<Product> = {
      name: draft.name,
      description: draft.description || '',
      domain_type: draft.domain_type ? Number(draft.domain_type) : undefined,
      status: draft.status ? Number(draft.status) : undefined,
      category: draft.category ? Number(draft.category) : null,
      uom: draft.uom ? Number(draft.uom) : null,
      manufacturer: draft.manufacturer ? Number(draft.manufacturer) : null,
      gost_drawing: draft.gost_drawing || '',
    };
    try {
      if (isEdit && target) {
        await updateMut.mutateAsync({ id: target.id, data: payload });
        toast.success(t('adminCatalog.updated'));
      } else {
        await createMut.mutateAsync(payload);
        toast.success(t('adminCatalog.created'));
      }
      onOpenChange(false);
    } catch {
      toast.error(t('adminCatalog.saveFailed'));
    }
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="overflow-y-auto sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>{isEdit ? t('adminCatalog.editProduct') : t('adminCatalog.newProduct')}</SheetTitle>
        </SheetHeader>

        <div className="mt-4 space-y-4 px-4">
          <div className="space-y-2">
            <Label>{t('adminCatalog.fields.name')}</Label>
            <Input value={draft.name ?? ''} onChange={(e) => update({ name: e.target.value })} />
          </div>
          <div className="space-y-2">
            <Label>{t('adminCatalog.fields.description')}</Label>
            <Textarea rows={3} value={draft.description ?? ''} onChange={(e) => update({ description: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.domainType')}</Label>
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
              <Label>{t('adminCatalog.fields.status')}</Label>
              <Select
                value={draft.status ? String(draft.status) : undefined}
                onValueChange={(v) => update({ status: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(statuses ?? []).map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.category')}</Label>
              <Select
                value={draft.category ? String(draft.category) : undefined}
                onValueChange={(v) => update({ category: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(categories ?? []).map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.uom')}</Label>
              <Select
                value={draft.uom ? String(draft.uom) : undefined}
                onValueChange={(v) => update({ uom: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(units ?? []).map((u) => (
                    <SelectItem key={u.id} value={String(u.id)}>{u.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.manufacturer')}</Label>
              <Select
                value={draft.manufacturer ? String(draft.manufacturer) : undefined}
                onValueChange={(v) => update({ manufacturer: Number(v) })}
              >
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {(manufacturers ?? []).map((m) => (
                    <SelectItem key={m.id} value={String(m.id)}>{m.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t('adminCatalog.fields.gost')}</Label>
              <Input value={draft.gost_drawing ?? ''} onChange={(e) => update({ gost_drawing: e.target.value })} />
            </div>
          </div>

          {isEdit && target?.sku && (
            <>
              <Separator />
              <div className="text-xs text-muted-foreground">
                {t('adminCatalog.fields.sku')}: <span className="font-mono">{target.sku}</span>
              </div>
            </>
          )}
        </div>

        <SheetFooter className="mt-6">
          <Button onClick={submit} disabled={busy} className="w-full">
            {isEdit ? t('adminCatalog.save') : t('adminCatalog.create')}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export function AdminCatalogPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [domainFilter, setDomainFilter] = useState<string>('all');
  const { data: products, isLoading } = useProducts({
    search: search || undefined,
    domain_type: domainFilter === 'all' ? undefined : domainFilter,
  });
  const { data: domainTypes } = useDomainTypes();
  const deleteMut = useDeleteProduct();

  const [sheetOpen, setSheetOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<Product | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Product | null>(null);

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
    try {
      await deleteMut.mutateAsync(deleteTarget.id);
      toast.success(t('adminCatalog.deleted'));
      setDeleteTarget(null);
    } catch {
      toast.error(t('adminCatalog.deleteFailed'));
    }
  };

  const stats = [
    { label: t('adminCatalog.stats.total'), value: String(products?.length ?? '—') },
    {
      label: t('adminCatalog.stats.published'),
      value: String(products?.filter((p) => p.status_name === 'PUBLISHED' || p.status_name?.toLowerCase().includes('публ')).length ?? '—'),
    },
    {
      label: t('adminCatalog.stats.draft'),
      value: String(products?.filter((p) => p.status_name === 'DRAFT' || p.status_name?.toLowerCase().includes('черн')).length ?? '—'),
    },
  ];

  return (
    <PageShell
      title={t('adminCatalog.title')}
      description={t('adminCatalog.description')}
      icon={<Package className="h-5 w-5" />}
      stats={stats}
      actions={[{ label: t('adminCatalog.newProduct'), onClick: onNew }]}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={t('adminCatalog.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={domainFilter} onValueChange={setDomainFilter}>
          <SelectTrigger className="w-full sm:w-60">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('adminCatalog.allDomains')}</SelectItem>
            {(domainTypes ?? []).map((d) => (
              <SelectItem key={d.id} value={d.code}>{d.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button onClick={onNew} className="gap-2">
          <Plus className="h-4 w-4" />
          {t('adminCatalog.newProduct')}
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? <LoadingRows rows={6} /> : !products?.length ? (
            <EmptyState icon={<Package className="h-5 w-5" />} message={t('adminCatalog.emptyState')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('adminCatalog.table.sku')}</TableHead>
                  <TableHead>{t('adminCatalog.table.name')}</TableHead>
                  <TableHead>{t('adminCatalog.table.domain')}</TableHead>
                  <TableHead>{t('adminCatalog.table.status')}</TableHead>
                  <TableHead>{t('adminCatalog.table.manufacturer')}</TableHead>
                  <TableHead className="text-right">{t('adminCatalog.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {products.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-mono text-xs">{p.sku ?? '—'}</TableCell>
                    <TableCell>{p.name}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">{p.domain_type_name || '—'}</TableCell>
                    <TableCell><Badge variant="outline">{p.status_name || '—'}</Badge></TableCell>
                    <TableCell className="text-muted-foreground text-xs">{p.manufacturer_data?.name ?? '—'}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => onEdit(p)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(p)}>
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ProductFormSheet open={sheetOpen} onOpenChange={setSheetOpen} target={editTarget} />

      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('adminCatalog.confirmDelete')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('adminCatalog.confirmDeleteDesc', { name: deleteTarget?.name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('adminCatalog.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete} disabled={deleteMut.isPending}>
              {t('adminCatalog.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageShell>
  );
}

export default AdminCatalogPage;
