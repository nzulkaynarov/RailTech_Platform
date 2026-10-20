import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Database, Plus, Pencil, Trash2, RotateCcw, Loader2 } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';

import { useDraftState } from '@/hooks/useDraftState';
import {
  useCountries,
  useCurrencies,
  useUnits,
  useDeliveryBases,
  useCreateLookup,
  useUpdateLookup,
  useDeleteLookup,
} from '@/hooks/useMasterData';
import type { MasterKind, Country, Currency, LookupItem } from '@/api/masterDataApi';
import { translateApiError } from '@/lib/apiError';

type AnyItem = Country | Currency | LookupItem;

function LookupEditor({
  kind,
  items,
  isLoading,
  isError,
  onRetry,
  extraFields = [],
  showInactive,
  onShowInactiveChange,
}: {
  kind: MasterKind;
  items: AnyItem[] | undefined;
  isLoading: boolean;
  isError?: boolean;
  onRetry?: () => void;
  extraFields?: { key: string; label: string }[];
  showInactive: boolean;
  onShowInactiveChange: (value: boolean) => void;
}) {
  const { t } = useTranslation();
  const createMut = useCreateLookup();
  const updateMut = useUpdateLookup();
  const deleteMut = useDeleteLookup();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<AnyItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AnyItem | null>(null);

  const draftSource = dialogOpen ? editTarget ?? 'new' : null;
  const [draft, setDraft] = useDraftState<typeof draftSource, Record<string, unknown>>(
    draftSource,
    (target) => (target && target !== 'new'
      ? { ...(target as unknown as Record<string, unknown>) }
      : { code: '', name: '', sort_order: 0, is_active: true }),
  );
  const [filter, setFilter] = useState('');

  const openNew = () => {
    setEditTarget(null);
    setDialogOpen(true);
  };

  const openEdit = (it: AnyItem) => {
    setEditTarget(it);
    setDialogOpen(true);
  };

  const submit = async () => {
    const code = (draft.code as string)?.trim();
    const name = (draft.name as string)?.trim();
    if (!code || !name) {
      toast.error(t('settings.masterData.requiredFields'));
      return;
    }
    try {
      if (editTarget) {
        await updateMut.mutateAsync({ kind, id: (editTarget as { id: number }).id, data: draft });
        toast.success(t('settings.masterData.updated'));
      } else {
        await createMut.mutateAsync({ kind, data: draft });
        toast.success(t('settings.masterData.created'));
      }
      setDialogOpen(false);
    } catch (e) {
      toast.error(translateApiError(e) || t('settings.masterData.saveFailed'));
    }
  };

  const onDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMut.mutateAsync({ kind, id: (deleteTarget as { id: number }).id });
      toast.success(t('settings.masterData.deleted'));
      setDeleteTarget(null);
    } catch (err) {
      toast.error(translateApiError(err));
    }
  };

  const restore = async (item: AnyItem) => {
    try {
      await updateMut.mutateAsync({ kind, id: (item as { id: number }).id, data: { is_active: true } });
      toast.success(t('settings.masterData.restored'));
    } catch (err) {
      toast.error(translateApiError(err));
    }
  };

  const visibleItems = (items ?? []).filter((it) => {
    if (!filter.trim()) return true;
    const rec = it as unknown as Record<string, unknown>;
    const haystack = `${rec.code ?? ''} ${rec.name ?? ''}`.toLowerCase();
    return haystack.includes(filter.trim().toLowerCase());
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={t('settings.masterData.filterPlaceholder')}
          className="max-w-xs"
          aria-label={t('settings.masterData.filterPlaceholder')}
        />
        <div className="flex items-center gap-2">
          <Switch
            id={`show-inactive-${kind}`}
            checked={showInactive}
            onCheckedChange={onShowInactiveChange}
          />
          <Label htmlFor={`show-inactive-${kind}`} className="text-xs text-muted-foreground cursor-pointer">
            {t('settings.masterData.showInactive')}
          </Label>
        </div>
        <Button onClick={openNew} className="gap-2 ml-auto">
          <Plus className="h-4 w-4" />
          {t('settings.masterData.new')}
        </Button>
      </div>

      {!isError && !isLoading && (
        <p className="text-xs text-muted-foreground" role="status">
          {t('settings.masterData.shownCount', { count: visibleItems.length })}
        </p>
      )}

      {isError ? (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
          <p className="text-sm text-destructive">{t('common.loadError')}</p>
          {onRetry && (
            <Button variant="outline" className="mt-3" onClick={onRetry}>
              {t('common.retry')}
            </Button>
          )}
        </div>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-32">{t('settings.masterData.code')}</TableHead>
                  <TableHead>{t('settings.masterData.name')}</TableHead>
                  {extraFields.map((f) => (
                    <TableHead key={f.key}>{f.label}</TableHead>
                  ))}
                  <TableHead className="w-24 text-right">{t('settings.masterData.sortOrder')}</TableHead>
                  <TableHead className="w-28">{t('settings.masterData.status')}</TableHead>
                  <TableHead className="w-24 text-right">{t('common.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell colSpan={5 + extraFields.length} className="text-center py-8">
                      <Loader2 className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                ) : visibleItems.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5 + extraFields.length} className="text-center py-8 text-muted-foreground">
                      {t('settings.masterData.empty')}
                    </TableCell>
                  </TableRow>
                ) : (
                  visibleItems.map((item) => {
                    const rec = item as unknown as Record<string, unknown>;
                    const isActive = Boolean(rec.is_active);
                    return (
                      <TableRow key={String(rec.id ?? rec.code)} className={!isActive ? 'opacity-60 bg-muted/20' : undefined}>
                        <TableCell className="font-mono font-medium">{String(rec.code)}</TableCell>
                        <TableCell>{String(rec.name)}</TableCell>
                        {extraFields.map((f) => (
                          <TableCell key={f.key}>{String(rec[f.key] ?? '—')}</TableCell>
                        ))}
                        <TableCell className="text-right font-mono">{String(rec.sort_order ?? 0)}</TableCell>
                        <TableCell>
                          <Badge variant={isActive ? 'default' : 'secondary'} className="text-xs">
                            {isActive ? t('common.active') : t('common.inactive')}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openEdit(item)}>
                              <Pencil className="h-4 w-4" />
                              <span className="sr-only">{t('common.edit')}</span>
                            </Button>
                            {isActive ? (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-destructive hover:bg-destructive/10"
                                onClick={() => setDeleteTarget(item)}
                              >
                                <Trash2 className="h-4 w-4" />
                                <span className="sr-only">{t('common.delete')}</span>
                              </Button>
                            ) : (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-primary"
                                onClick={() => restore(item)}
                              >
                                <RotateCcw className="h-4 w-4" />
                                <span className="sr-only">{t('common.restore')}</span>
                              </Button>
                            )}
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

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {editTarget ? t('settings.masterData.editTitle') : t('settings.masterData.createTitle')}
            </DialogTitle>
            <DialogDescription>
              {editTarget ? t('settings.masterData.editDesc') : t('settings.masterData.createDesc')}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="item-code">{t('settings.masterData.code')}</Label>
              <Input
                id="item-code"
                value={(draft.code as string) ?? ''}
                onChange={(e) => setDraft({ ...draft, code: e.target.value })}
                disabled={Boolean(editTarget)}
                placeholder="USD"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="item-name">{t('settings.masterData.name')}</Label>
              <Input
                id="item-name"
                value={(draft.name as string) ?? ''}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder={t('settings.masterData.namePlaceholder')}
              />
            </div>
            {extraFields.map((f) => (
              <div key={f.key} className="space-y-2">
                <Label htmlFor={`extra-${f.key}`}>{f.label}</Label>
                <Input
                  id={`extra-${f.key}`}
                  value={(draft[f.key] as string) ?? ''}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                />
              </div>
            ))}
            <div className="space-y-2">
              <Label htmlFor="item-sort">{t('settings.masterData.sortOrder')}</Label>
              <Input
                id="item-sort"
                type="number"
                value={(draft.sort_order as number) ?? 0}
                onChange={(e) => setDraft({ ...draft, sort_order: Number(e.target.value) })}
              />
            </div>
            <div className="flex items-center gap-2 pt-2">
              <Switch
                id="item-is-active"
                checked={Boolean(draft.is_active)}
                onCheckedChange={(v) => setDraft({ ...draft, is_active: v })}
              />
              <Label htmlFor="item-is-active" className="text-sm font-medium cursor-pointer">
                {t('common.active')}
              </Label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={submit} disabled={createMut.isPending || updateMut.isPending}>
              {(createMut.isPending || updateMut.isPending) && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              {editTarget ? t('common.save') : t('common.create')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation */}
      <AlertDialog open={Boolean(deleteTarget)} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('settings.masterData.confirmDeleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('settings.masterData.confirmDeleteDesc', {
                code: (deleteTarget as unknown as Record<string, unknown>)?.code,
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={onDelete} disabled={deleteMut.isPending}>
              {t('common.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export function MasterDataSettings() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<MasterKind>('currencies');

  const [showInactiveCurrencies, setShowInactiveCurrencies] = useState(false);
  const [showInactiveUnits, setShowInactiveUnits] = useState(false);
  const [showInactiveCountries, setShowInactiveCountries] = useState(false);
  const [showInactiveBases, setShowInactiveBases] = useState(false);

  const {
    data: currencies,
    isLoading: loadingCurrencies,
    isError: errorCurrencies,
    refetch: refetchCurrencies,
  } = useCurrencies(showInactiveCurrencies);

  const {
    data: units,
    isLoading: loadingUnits,
    isError: errorUnits,
    refetch: refetchUnits,
  } = useUnits(showInactiveUnits);

  const {
    data: countries,
    isLoading: loadingCountries,
    isError: errorCountries,
    refetch: refetchCountries,
  } = useCountries(showInactiveCountries);

  const {
    data: deliveryBases,
    isLoading: loadingBases,
    isError: errorBases,
    refetch: refetchBases,
  } = useDeliveryBases(showInactiveBases);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <Database className="h-5 w-5 text-primary" />
          {t('settings.masterData.title')}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">{t('settings.masterData.subtitle')}</p>
      </div>

      <Tabs value={tab} onValueChange={(v) => setTab(v as MasterKind)}>
        <TabsList className="grid grid-cols-4 w-full sm:w-auto">
          <TabsTrigger value="currencies">{t('settings.masterData.tabs.currencies')}</TabsTrigger>
          <TabsTrigger value="units">{t('settings.masterData.tabs.units')}</TabsTrigger>
          <TabsTrigger value="countries">{t('settings.masterData.tabs.countries')}</TabsTrigger>
          <TabsTrigger value="delivery-basis">{t('settings.masterData.tabs.deliveryBases')}</TabsTrigger>
        </TabsList>

        <TabsContent value="currencies" className="mt-6">
          <LookupEditor
            kind="currencies"
            items={currencies}
            isLoading={loadingCurrencies}
            isError={errorCurrencies}
            onRetry={refetchCurrencies}
            extraFields={[
              { key: 'symbol', label: t('settings.masterData.symbol') },
            ]}
            showInactive={showInactiveCurrencies}
            onShowInactiveChange={setShowInactiveCurrencies}
          />
        </TabsContent>

        <TabsContent value="units" className="mt-6">
          <LookupEditor
            kind="units"
            items={units}
            isLoading={loadingUnits}
            isError={errorUnits}
            onRetry={refetchUnits}
            showInactive={showInactiveUnits}
            onShowInactiveChange={setShowInactiveUnits}
          />
        </TabsContent>

        <TabsContent value="countries" className="mt-6">
          <LookupEditor
            kind="countries"
            items={countries}
            isLoading={loadingCountries}
            isError={errorCountries}
            onRetry={refetchCountries}
            extraFields={[
              { key: 'iso_numeric', label: t('settings.masterData.isoNumeric') },
            ]}
            showInactive={showInactiveCountries}
            onShowInactiveChange={setShowInactiveCountries}
          />
        </TabsContent>

        <TabsContent value="delivery-basis" className="mt-6">
          <LookupEditor
            kind="delivery-basis"
            items={deliveryBases}
            isLoading={loadingBases}
            isError={errorBases}
            onRetry={refetchBases}
            showInactive={showInactiveBases}
            onShowInactiveChange={setShowInactiveBases}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default MasterDataSettings;
