import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Database, Plus, Pencil, Trash2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from '@/components/ui/sheet';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { PageShell, LoadingRows, EmptyState, ErrorState } from './shared/PageShell';
import {
  useCountries, useCurrencies, useUnits, useDeliveryBases,
  useCreateLookup, useUpdateLookup, useDeleteLookup,
} from '@/hooks/useMasterData';
import type { MasterKind, Country, Currency, LookupItem } from '@/api/masterDataApi';

type AnyItem = Country | Currency | LookupItem;

function LookupEditor({
  kind, items, isLoading, isError, onRetry, extraFields = [],
}: {
  kind: MasterKind;
  items: AnyItem[] | undefined;
  isLoading: boolean;
  isError?: boolean;
  onRetry?: () => void;
  extraFields?: { key: string; label: string }[];
}) {
  const { t } = useTranslation();
  const createMut = useCreateLookup();
  const updateMut = useUpdateLookup();
  const deleteMut = useDeleteLookup();

  const [sheetOpen, setSheetOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<AnyItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AnyItem | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [filter, setFilter] = useState('');

  useEffect(() => {
    if (editTarget) {
      setDraft({ ...editTarget as unknown as Record<string, unknown> });
    } else {
      setDraft({ code: '', name: '', sort_order: 0, is_active: true });
    }
  }, [editTarget]);

  const openNew = () => { setEditTarget(null); setSheetOpen(true); };
  const openEdit = (it: AnyItem) => { setEditTarget(it); setSheetOpen(true); };

  const submit = async () => {
    const code = (draft.code as string)?.trim();
    const name = (draft.name as string)?.trim();
    if (!code || !name) {
      toast.error(t('adminMasterData.requiredFields'));
      return;
    }
    try {
      if (editTarget) {
        await updateMut.mutateAsync({ kind, id: (editTarget as { id: number }).id, data: draft });
        toast.success(t('adminMasterData.updated'));
      } else {
        await createMut.mutateAsync({ kind, data: draft });
        toast.success(t('adminMasterData.created'));
      }
      setSheetOpen(false);
    } catch {
      toast.error(t('adminMasterData.saveFailed'));
    }
  };

  const onDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMut.mutateAsync({ kind, id: (deleteTarget as { id: number }).id });
      toast.success(t('adminMasterData.deleted'));
      setDeleteTarget(null);
    } catch {
      toast.error(t('adminMasterData.deleteFailed'));
    }
  };

  // Справочники перестали быть короткими: стран после наполнения по ISO 3166-1 — 249,
  // и таблица без фильтра превращается в прокрутку. Фильтр общий для всех вкладок.
  const visibleItems = (items ?? []).filter((it) => {
    if (!filter.trim()) return true;
    const rec = it as unknown as Record<string, unknown>;
    const haystack = `${rec.code ?? ''} ${rec.name ?? ''}`.toLowerCase();
    return haystack.includes(filter.trim().toLowerCase());
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={t('adminMasterData.filterPlaceholder')}
          className="max-w-xs"
          aria-label={t('adminMasterData.filterPlaceholder')}
        />
        <Button onClick={openNew} className="gap-2 ml-auto">
          <Plus className="h-4 w-4" />
          {t('adminMasterData.new')}
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {isError ? <ErrorState onRetry={onRetry} /> : isLoading ? <LoadingRows rows={5} /> : !visibleItems.length ? (
            <EmptyState icon={<Database className="h-5 w-5" />} message={t('adminMasterData.empty')} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('adminMasterData.fields.code')}</TableHead>
                  <TableHead>{t('adminMasterData.fields.name')}</TableHead>
                  {extraFields.map((f) => (
                    <TableHead key={f.key}>{f.label}</TableHead>
                  ))}
                  <TableHead>{t('adminMasterData.fields.sortOrder')}</TableHead>
                  <TableHead>{t('adminMasterData.fields.isActive')}</TableHead>
                  <TableHead className="text-right">{t('adminMasterData.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleItems.map((it) => {
                  const rec = it as unknown as Record<string, unknown>;
                  return (
                    <TableRow key={(it as { id: number }).id}>
                      <TableCell className="font-mono text-xs">{String(rec.code ?? '—')}</TableCell>
                      <TableCell>{String(rec.name ?? '—')}</TableCell>
                      {extraFields.map((f) => (
                        <TableCell key={f.key} className="text-muted-foreground text-xs">
                          {String(rec[f.key] ?? '—')}
                        </TableCell>
                      ))}
                      <TableCell className="text-muted-foreground text-xs">
                        {String(rec.sort_order ?? 0)}
                      </TableCell>
                      <TableCell className="text-xs">
                        {rec.is_active ? t('adminMasterData.yes') : t('adminMasterData.no')}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="sm" onClick={() => openEdit(it)}>
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(it)}>
                            <Trash2 className="h-3.5 w-3.5 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent className="sm:max-w-md">
          <SheetHeader>
            <SheetTitle>{editTarget ? t('adminMasterData.edit') : t('adminMasterData.new')}</SheetTitle>
          </SheetHeader>

          <div className="mt-4 space-y-4 px-4">
            <div className="space-y-2">
              <Label>{t('adminMasterData.fields.code')}</Label>
              <Input
                value={String(draft.code ?? '')}
                onChange={(e) => setDraft((d) => ({ ...d, code: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <Label>{t('adminMasterData.fields.name')}</Label>
              <Input
                value={String(draft.name ?? '')}
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
              />
            </div>
            {extraFields.map((f) => (
              <div key={f.key} className="space-y-2">
                <Label>{f.label}</Label>
                <Input
                  value={String(draft[f.key] ?? '')}
                  onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                />
              </div>
            ))}
            <div className="space-y-2">
              <Label>{t('adminMasterData.fields.sortOrder')}</Label>
              <Input
                type="number"
                value={Number(draft.sort_order ?? 0)}
                onChange={(e) => setDraft((d) => ({ ...d, sort_order: Number(e.target.value) }))}
              />
            </div>
            <div className="flex items-center justify-between rounded-lg border p-3">
              <Label>{t('adminMasterData.fields.isActive')}</Label>
              <Switch
                checked={Boolean(draft.is_active ?? true)}
                onCheckedChange={(v) => setDraft((d) => ({ ...d, is_active: v }))}
              />
            </div>
          </div>

          <SheetFooter className="mt-6">
            <Button onClick={submit} disabled={createMut.isPending || updateMut.isPending} className="w-full">
              {editTarget ? t('adminMasterData.save') : t('adminMasterData.create')}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('adminMasterData.confirmDelete')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('adminMasterData.confirmDeleteDesc', { code: String((deleteTarget as unknown as Record<string, unknown>)?.code ?? '') })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('adminMasterData.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete} disabled={deleteMut.isPending}>
              {t('adminMasterData.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export function AdminMasterDataPage() {
  const { t } = useTranslation();
  const countries = useCountries();
  const currencies = useCurrencies();
  const units = useUnits();
  const deliveryBases = useDeliveryBases();

  const stats = useMemo(() => [
    { label: t('adminMasterData.stats.countries'), value: String(countries.data?.length ?? '—') },
    { label: t('adminMasterData.stats.currencies'), value: String(currencies.data?.length ?? '—') },
    { label: t('adminMasterData.stats.units'), value: String(units.data?.length ?? '—') },
    { label: t('adminMasterData.stats.deliveryBases'), value: String(deliveryBases.data?.length ?? '—') },
  ], [countries.data, currencies.data, units.data, deliveryBases.data, t]);

  return (
    <PageShell
      title={t('adminMasterData.title')}
      description={t('adminMasterData.description')}
      icon={<Database className="h-5 w-5" />}
      stats={stats}
    >
      <Tabs defaultValue="countries">
        <TabsList>
          <TabsTrigger value="countries">{t('adminMasterData.tabs.countries')}</TabsTrigger>
          <TabsTrigger value="currencies">{t('adminMasterData.tabs.currencies')}</TabsTrigger>
          <TabsTrigger value="units">{t('adminMasterData.tabs.units')}</TabsTrigger>
          <TabsTrigger value="delivery-basis">{t('adminMasterData.tabs.deliveryBasis')}</TabsTrigger>
        </TabsList>

        <TabsContent value="countries" className="mt-4">
          <LookupEditor
            kind="countries"
            items={countries.data}
            isLoading={countries.isLoading}
            isError={countries.isError}
            onRetry={() => countries.refetch()}
            extraFields={[
              { key: 'alpha2', label: t('adminMasterData.countryFields.alpha2') },
              { key: 'iso_numeric', label: t('adminMasterData.countryFields.isoNumeric') },
              { key: 'vat_rate', label: t('adminMasterData.countryFields.vatRate') },
            ]}
          />
        </TabsContent>

        <TabsContent value="currencies" className="mt-4">
          <LookupEditor
            kind="currencies"
            items={currencies.data}
            isLoading={currencies.isLoading}
            isError={currencies.isError}
            onRetry={() => currencies.refetch()}
            extraFields={[{ key: 'symbol', label: t('adminMasterData.currencyFields.symbol') }]}
          />
        </TabsContent>

        <TabsContent value="units" className="mt-4">
          <LookupEditor kind="units" items={units.data} isLoading={units.isLoading} isError={units.isError} onRetry={() => units.refetch()} />
        </TabsContent>

        <TabsContent value="delivery-basis" className="mt-4">
          <LookupEditor kind="delivery-basis" items={deliveryBases.data} isLoading={deliveryBases.isLoading} isError={deliveryBases.isError} onRetry={() => deliveryBases.refetch()} />
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}

export default AdminMasterDataPage;
