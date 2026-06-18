import { useState, Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2, PackagePlus, AlertTriangle, Send, Upload } from 'lucide-react';
import { toast } from 'sonner';
import type { QuoteItem } from '@/api/crmApi';
import { useAddRequestItem, useUpdateQuoteItem, useDeleteQuoteItem, useSubmitRequest } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ImportRequestDialog } from '@/components/CRM/ImportRequestDialog';
import { useUnits } from '@/hooks/useMasterData';

/**
 * Editable buyer request (заявка) line items. The buyer owns WHAT they want to
 * procure; pricing is the seller's job and never shown here. Editing (name +
 * quantity) is allowed only while `canEdit` (the seller hasn't taken the deal
 * into work — backend enforces it via `can_edit_request`). Rows are saved on
 * blur to keep the grid calm under React-Query refetches.
 */
export function RequestItemsEditor({
  dealId,
  items,
  canEdit,
}: {
  dealId: number;
  items: QuoteItem[];
  canEdit: boolean;
}) {
  const { t } = useTranslation();
  const addItem = useAddRequestItem();
  const updateItem = useUpdateQuoteItem();
  const deleteItem = useDeleteQuoteItem();
  const submitRequest = useSubmitRequest();

  const { data: units, isLoading: unitsLoading } = useUnits();
  const [newName, setNewName] = useState('');
  const [newQty, setNewQty] = useState('1');
  const [newUnit, setNewUnit] = useState('');
  const [importOpen, setImportOpen] = useState(false);

  const unitName = (code?: string) => units?.find((u) => u.code === code)?.name || '';

  const saveUnit = async (item: QuoteItem, code: string) => {
    try {
      await updateItem.mutateAsync({ id: item.id, data: { unit_code: code, unit: unitName(code) } });
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };
  const saveNote = async (item: QuoteItem, value: string) => {
    if (value.trim() === (item.note || '').trim()) return;
    try {
      await updateItem.mutateAsync({ id: item.id, data: { note: value } });
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };
  const saveMpn = async (item: QuoteItem, value: string) => {
    if (value.trim() === (item.mpn || '').trim()) return;
    try {
      await updateItem.mutateAsync({ id: item.id, data: { mpn: value.trim() } });
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };
  const saveGtin = async (item: QuoteItem, value: string) => {
    if (value.trim() === (item.gtin || '').trim()) return;
    try {
      await updateItem.mutateAsync({ id: item.id, data: { gtin: value.trim() } });
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const itemName = (item: QuoteItem) => item.product_name || item.imported_raw_name || '';
  const hasIncomplete = items.some((item) => item.is_incomplete);
  const isEmpty = items.length === 0;

  const handleSubmit = async () => {
    try {
      await submitRequest.mutateAsync(dealId);
      toast.success(t('requestItems.submittedToast'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const handleAdd = async () => {
    const name = newName.trim();
    if (!name) {
      toast.error(t('requestItems.nameRequired'));
      return;
    }
    try {
      await addItem.mutateAsync({
        dealId,
        name,
        quantity: Math.max(1, Number(newQty) || 1),
        unit_code: newUnit,
        unit: unitName(newUnit),
      });
      setNewName('');
      setNewQty('1');
      setNewUnit('');
      toast.success(t('requestItems.added'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const saveName = async (item: QuoteItem, value: string) => {
    const name = value.trim();
    if (!name || name === itemName(item)) return;
    try {
      await updateItem.mutateAsync({ id: item.id, data: { imported_raw_name: name } });
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const saveQty = async (item: QuoteItem, value: string) => {
    const qty = Math.max(1, Number(value) || 1);
    if (qty === item.quantity) return;
    try {
      await updateItem.mutateAsync({ id: item.id, data: { quantity: qty } });
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const remove = async (item: QuoteItem) => {
    try {
      await deleteItem.mutateAsync(item.id);
      toast.success(t('requestItems.removed'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2">
              <PackagePlus className="h-5 w-5 text-primary" />
              {t('requestItems.title')}
            </CardTitle>
            <CardDescription>
              {canEdit ? t('requestItems.subtitleEditable') : t('requestItems.subtitleLocked')}
            </CardDescription>
          </div>
          {canEdit && (
            <Button variant="outline" size="sm" className="shrink-0 gap-1.5" onClick={() => setImportOpen(true)}>
              <Upload className="h-4 w-4" />
              {t('requestItems.uploadFile')}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
        <Table className="min-w-[28rem]">
          <TableHeader>
            <TableRow className="bg-muted/50">
              <TableHead className="w-10 text-center">{t('requestItems.numCol')}</TableHead>
              <TableHead>{t('requestItems.nameCol')}</TableHead>
              <TableHead className="w-24">{t('requestItems.unitCol')}</TableHead>
              <TableHead className="w-28 text-right">{t('requestItems.qtyCol')}</TableHead>
              {canEdit && <TableHead className="w-12" />}
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item, index) => (
              <Fragment key={item.id}>
              <TableRow className={item.is_incomplete ? 'border-0 bg-destructive/5' : 'border-0'}>
                <TableCell className="text-center align-top text-sm text-muted-foreground tabular-nums">
                  {index + 1}
                </TableCell>
                <TableCell>
                  {/* A catalog-linked row's name is authoritative (product_name);
                      editing imported_raw_name would be a silent no-op since
                      itemName() prefers product_name. Show it read-only with a
                      «from catalog» badge instead of a deceptively-editable field. */}
                  {canEdit && !item.product_name ? (
                    <Textarea
                      defaultValue={itemName(item)}
                      onBlur={(e) => saveName(item, e.target.value)}
                      rows={1}
                      className="min-h-8 resize-none py-1.5 field-sizing-content"
                      aria-label={t('requestItems.nameCol')}
                    />
                  ) : (
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{itemName(item)}</span>
                      {canEdit && item.product_name && (
                        <Badge variant="secondary" className="font-normal">{t('requestItems.fromCatalog')}</Badge>
                      )}
                    </span>
                  )}
                  {!canEdit && item.mpn && (
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {t('requestItems.skuLabel')}: <span className="font-mono">{item.mpn}</span>
                    </span>
                  )}
                  {item.is_incomplete && (
                    <Badge variant="destructive" className="mt-1">
                      <AlertTriangle className="size-3" aria-hidden="true" />
                      {t('requestItems.incomplete')}
                    </Badge>
                  )}
                </TableCell>
                <TableCell>
                  {canEdit ? (
                    <Select value={item.unit_code || ''} onValueChange={(v) => saveUnit(item, v)}>
                      {/* Legacy/parser imports populate the free-text `unit`
                          ("штук") but no UN/ECE `unit_code`. Bind the Select to
                          the code, yet fall back to the stored free-text as the
                          trigger label so the buyer still SEES their unit
                          instead of an empty "—". */}
                      <SelectTrigger className="h-8 w-24" disabled={unitsLoading && !item.unit}>
                        <SelectValue placeholder={unitsLoading ? t('common.loading') : (item.unit || '—')} />
                      </SelectTrigger>
                      <SelectContent>
                        {(units ?? []).map((u) => (
                          <SelectItem key={u.code} value={u.code}>{u.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <span className="text-sm text-muted-foreground">{item.unit || '—'}</span>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  {canEdit ? (
                    <Input
                      type="number"
                      min={1}
                      defaultValue={item.quantity}
                      onBlur={(e) => saveQty(item, e.target.value)}
                      className="h-8 text-right tabular-nums"
                      aria-label={t('requestItems.qtyCol')}
                    />
                  ) : (
                    <span className="tabular-nums">{item.quantity}</span>
                  )}
                </TableCell>
                {canEdit && (
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      onClick={() => remove(item)}
                      disabled={deleteItem.isPending}
                      title={t('common.delete')}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                )}
              </TableRow>
              {/* Note sub-row — full width, so it never collides with Unit/Qty. */}
              {(canEdit || item.note) && (
                <TableRow className={item.is_incomplete ? 'bg-destructive/5 hover:bg-destructive/5' : 'hover:bg-transparent'}>
                  <TableCell className="pt-0" />
                  <TableCell colSpan={canEdit ? 4 : 3} className="pt-0">
                    {canEdit ? (
                      <div className="flex flex-wrap gap-2">
                        <Input
                          defaultValue={item.mpn || ''}
                          onBlur={(e) => saveMpn(item, e.target.value)}
                          placeholder={t('requestItems.skuPlaceholder')}
                          className="h-7 w-36 text-xs"
                          aria-label={t('requestItems.skuLabel')}
                        />
                        <Input
                          defaultValue={item.gtin || ''}
                          onBlur={(e) => saveGtin(item, e.target.value)}
                          placeholder={t('requestItems.gtinPlaceholder')}
                          className="h-7 w-32 text-xs"
                          aria-label="GTIN"
                        />
                        <Input
                          defaultValue={item.note || ''}
                          onBlur={(e) => saveNote(item, e.target.value)}
                          placeholder={t('requestItems.notePlaceholder')}
                          className="h-7 flex-1 text-xs"
                          aria-label={t('requestItems.noteCol')}
                        />
                      </div>
                    ) : (
                      <span className="block whitespace-pre-line text-xs text-muted-foreground">{item.note}</span>
                    )}
                  </TableCell>
                </TableRow>
              )}
              </Fragment>
            ))}
            {items.length === 0 && (
              <TableRow>
                <TableCell colSpan={canEdit ? 5 : 4} className="text-center py-6 text-muted-foreground">
                  {t('requestItems.empty')}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        </div>

        {canEdit && (
          <div className="mt-4 flex flex-wrap items-end gap-2">
            <div className="min-w-40 flex-1">
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); }}
                placeholder={t('requestItems.namePlaceholder')}
                aria-label={t('requestItems.namePlaceholder')}
              />
            </div>
            <Select value={newUnit} onValueChange={setNewUnit}>
              <SelectTrigger className="w-24"><SelectValue placeholder={t('requestItems.unitCol')} /></SelectTrigger>
              <SelectContent>
                {(units ?? []).map((u) => (
                  <SelectItem key={u.code} value={u.code}>{u.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              type="number"
              min={1}
              value={newQty}
              onChange={(e) => setNewQty(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleAdd(); }}
              className="w-24 text-right tabular-nums"
              aria-label={t('requestItems.qtyCol')}
            />
            <Button onClick={handleAdd} disabled={addItem.isPending}>
              <Plus className="h-4 w-4 mr-1.5" />
              {t('requestItems.add')}
            </Button>
          </div>
        )}

        {/* Submit the RFQ to the seller — the «Отправить заявку» step. Gated by
            the data-quality rule: ≥1 line and no incomplete lines. */}
        {canEdit && (
          <div className="mt-6 flex flex-col gap-2 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-muted-foreground">
              {isEmpty
                ? t('requestItems.submitHintEmpty')
                : hasIncomplete
                  ? t('requestItems.submitHintIncomplete')
                  : t('requestItems.submitHint')}
            </p>
            <Button
              onClick={handleSubmit}
              disabled={isEmpty || hasIncomplete || submitRequest.isPending}
              className="sm:w-auto"
            >
              <Send className="h-4 w-4 mr-1.5" />
              {t('requestItems.submit')}
            </Button>
          </div>
        )}
      </CardContent>

      {canEdit && <ImportRequestDialog dealId={dealId} open={importOpen} onOpenChange={setImportOpen} />}
    </Card>
  );
}
