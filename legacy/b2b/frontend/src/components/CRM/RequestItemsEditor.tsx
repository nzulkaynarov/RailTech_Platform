import { useState, useEffect, useMemo, Fragment } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2, PackagePlus, AlertTriangle, Send, Upload, Sparkles, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import type { QuoteItem, SuggestedSeller } from '@/api/crmApi';
import { useAddRequestItem, useUpdateQuoteItem, useDeleteQuoteItem, useSubmitRequest, useRouteDeal, useSuggestedSellers, useSuggestSellersAi } from '@/hooks/useCRM';
import { usePartnerSuppliers } from '@/hooks/useAccounts';
import { translateApiError } from '@/lib/apiError';
import { ConfirmActionDialog } from '@/components/Shared/ConfirmActionDialog';
import { uomLabelKey } from '@/lib/codes';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Checkbox } from '@/components/ui/checkbox';
import { ImportRequestDialog } from '@/components/CRM/ImportRequestDialog';
import { ConversationalRequest } from '@/components/Sourcing/ConversationalRequest';
import { useUnits } from '@/hooks/useMasterData';

// `name_canonical` is the AI-import's normalised RU search key on QuoteItem. The
// shared QuoteItem type/serializer expose it (see crmApi.ts delta); this local
// view keeps the editor compiling independently of that single-writer file while
// avoiding `any`.
type RequestItem = QuoteItem & { name_canonical?: string };

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
  hasRecipients = false,
}: {
  dealId: number;
  items: RequestItem[];
  canEdit: boolean;
  /** True when the deal is already routed to ≥1 seller (catalog lines or a prior
      explicit routing). A free-text заявка has no implied seller, so submit first
      opens the supplier picker — otherwise the backend rejects with NO_RECIPIENTS. */
  hasRecipients?: boolean;
}) {
  const { t } = useTranslation();
  const addItem = useAddRequestItem();
  const updateItem = useUpdateQuoteItem();
  const deleteItem = useDeleteQuoteItem();
  const submitRequest = useSubmitRequest();
  const routeDeal = useRouteDeal();

  const { data: units, isLoading: unitsLoading } = useUnits();
  const [newName, setNewName] = useState('');
  const [newQty, setNewQty] = useState('1');
  const [newUnit, setNewUnit] = useState('');
  const [importOpen, setImportOpen] = useState(false);
  const [pendingRemoval, setPendingRemoval] = useState<QuoteItem | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedSellerIds, setSelectedSellerIds] = useState<number[]>([]);
  // The catalog-implied routing happens server-side at submit, so client-side we only
  // know about EXPLICIT routings (hasRecipients) or catalog-linked lines (product set).
  const hasCatalogLines = items.some((item) => item.product != null);
  const { data: suppliers, isLoading: suppliersLoading } = usePartnerSuppliers(pickerOpen);
  // R1 — предложенные продавцы по позициям заявки (мгновенный trigram); грузим при открытии пикера.
  const { data: suggested } = useSuggestedSellers(dealId, pickerOpen);
  // R3 — опциональное AI-усиление подбора (покупатель запускает явно); мержим на клиенте.
  const suggestAi = useSuggestSellersAi();
  const [aiSellers, setAiSellers] = useState<SuggestedSeller[] | null>(null);
  // Сбрасываем AI-результат при (пере)открытии пикера, чтобы не показывать чужой прогон.
  useEffect(() => { if (!pickerOpen) setAiSellers(null); }, [pickerOpen]);
  // Итоговые подсказки = trigram ∪ AI (по компании берём бо́льший счёт совпадений).
  const mergedSuggested = useMemo(() => {
    const byId = new Map<number, SuggestedSeller>();
    for (const seller of suggested ?? []) byId.set(seller.company_id, seller);
    for (const seller of aiSellers ?? []) {
      const existing = byId.get(seller.company_id);
      if (!existing || seller.matched_lines > existing.matched_lines) byId.set(seller.company_id, seller);
    }
    return [...byId.values()];
  }, [suggested, aiSellers]);
  const suggestedById = new Map(mergedSuggested.map((s) => [s.company_id, s]));
  // Предвыбор: когда подсказка пришла (или AI её дополнил) и покупатель ещё ничего не трогал — отмечаем совпавших.
  const [touchedPicker, setTouchedPicker] = useState(false);
  useEffect(() => {
    if (pickerOpen && !touchedPicker && mergedSuggested.length > 0) {
      setSelectedSellerIds(mergedSuggested.map((s) => s.company_id));
    }
  }, [pickerOpen, touchedPicker, mergedSuggested]);

  const runAiSuggest = async () => {
    try {
      const { sellers } = await suggestAi.mutateAsync(dealId);
      setAiSellers(sellers);
      const knownIds = new Set((suggested ?? []).map((s) => s.company_id));
      const added = sellers.filter((s) => !knownIds.has(s.company_id)).length;
      toast[added > 0 ? 'success' : 'info'](
        added > 0 ? t('requestItems.aiSuggestAdded', { count: added }) : t('requestItems.aiSuggestNoneNew'),
      );
    } catch (error) {
      toast.error(translateApiError(error));
    }
  };
  // Совпавшие продавцы — вверх списка, чтобы покупатель видел их первыми.
  const orderedSuppliers = [...(suppliers ?? [])].sort(
    (a, b) => (suggestedById.get(b.id)?.matched_lines ?? 0) - (suggestedById.get(a.id)?.matched_lines ?? 0),
  );

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
  // For the buyer it's all just "the part code" (артикул or ГОСТ/чертёж — see
  // [[feedback]]). We expose ONE field and auto-classify: a ГОСТ/ОСТ/ТУ/чертёж marker
  // or a drawing-number pattern → gost_drawing, otherwise a manufacturer part number.
  const looksLikeGost = (v: string) =>
    /(гост|gost|ост\s|\bту\b|чертёж|чертеж|drawing)/i.test(v) || /^\d{1,4}[.-]\d/.test(v.trim());
  const partCode = (item: QuoteItem) => item.gost_drawing || item.mpn || '';
  const saveCode = async (item: QuoteItem, value: string) => {
    const v = value.trim();
    if (v === partCode(item).trim()) return;
    // One code per line: set the classified field, clear the other (single source).
    const data = looksLikeGost(v) ? { gost_drawing: v, mpn: '' } : { mpn: v, gost_drawing: '' };
    try {
      await updateItem.mutateAsync({ id: item.id, data });
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const itemName = (item: QuoteItem) => item.product_name || item.imported_raw_name || '';
  const hasIncomplete = items.some((item) => item.is_incomplete);
  const isEmpty = items.length === 0;

  const doSubmit = async () => {
    try {
      await submitRequest.mutateAsync(dealId);
      toast.success(t('requestItems.submittedToast'));
      setPickerOpen(false);
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const handleSubmit = async () => {
    // A free-text заявка reaches no seller by itself — ask WHO to send it to first.
    if (!hasRecipients && !hasCatalogLines) {
      setPickerOpen(true);
      return;
    }
    await doSubmit();
  };

  const handleRouteAndSubmit = async () => {
    try {
      await routeDeal.mutateAsync({ dealId, sellerCompanyIds: selectedSellerIds });
    } catch (e) {
      toast.error(translateApiError(e));
      return;
    }
    await doSubmit();
  };

  const toggleSeller = (id: number) => {
    setTouchedPicker(true);  // покупатель сам управляет выбором — больше не перетираем предвыбором
    setSelectedSellerIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
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

  // Canonical search name set by the AI import (normalised RU spelling used as the
  // catalog-search key). The buyer may view/correct it so a mistranslated line can
  // still be matched — it never overwrites the original imported_raw_name.
  const saveCanonical = async (item: RequestItem, value: string) => {
    const canonical = value.trim();
    if (canonical === (item.name_canonical || '').trim()) return;
    try {
      await updateItem.mutateAsync({
        id: item.id,
        data: { name_canonical: canonical } as Partial<QuoteItem>,
      });
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

  // Удаление позиции необратимо и меняет состав заявки — раньше уходило с первого клика
  // по иконке в узкой строке таблицы (аудит UI, U4).
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
      <ConfirmActionDialog
        open={pendingRemoval !== null}
        onOpenChange={(open) => !open && setPendingRemoval(null)}
        title={t('requestItems.removeConfirmTitle')}
        description={t('requestItems.removeConfirmDescription', {
          name: pendingRemoval?.imported_raw_name || pendingRemoval?.product_name || '',
        })}
        variant="destructive"
        confirmLabel={t('common.delete')}
        onConfirm={async () => {
          const target = pendingRemoval;
          setPendingRemoval(null);
          if (target) await remove(target);
        }}
      />
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
                  {canEdit && (
                    <Input
                      key={item.name_canonical}
                      defaultValue={item.name_canonical || ''}
                      onBlur={(e) => saveCanonical(item, e.target.value)}
                      placeholder={t('requestItems.searchNamePlaceholder')}
                      className="mt-1 h-7 text-xs"
                      aria-label={t('requestItems.searchNameLabel')}
                    />
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
                    <div className="flex items-center gap-1">
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
                          <SelectItem key={u.code} value={u.code}>{uomLabelKey(u.code) ? t(uomLabelKey(u.code)) : u.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {/* Free-text unit with no UN/ECE code — fine to display, but
                        nudge normalisation since it feeds the seller's КП/automation. */}
                    {item.unit && !item.unit_code && (
                      <span title={t('requestItems.unitNotNormalized')} className="inline-flex">
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warning" aria-label={t('requestItems.unitNotNormalized')} />
                      </span>
                    )}
                    </div>
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
                      onClick={() => setPendingRemoval(item)}
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
                      <div className="flex flex-wrap items-start gap-2">
                        <Input
                          key={partCode(item)}
                          defaultValue={partCode(item)}
                          onBlur={(e) => saveCode(item, e.target.value)}
                          placeholder={t('requestItems.codePlaceholder')}
                          className="h-7 w-44 text-xs"
                          aria-label={t('requestItems.codeLabel')}
                        />
                        <Textarea
                          defaultValue={item.note || ''}
                          onBlur={(e) => saveNote(item, e.target.value)}
                          placeholder={t('requestItems.notePlaceholder')}
                          className="min-h-7 flex-1 resize-y text-xs"
                          rows={1}
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

        {/* AI #8 — describe the need in words; the buyer accepts proposed lines
            into the grid (human-in-loop, nothing auto-submitted). */}
        {canEdit && (
          <div className="mt-4">
            <ConversationalRequest dealId={dealId} />
          </div>
        )}

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
                  <SelectItem key={u.code} value={u.code}>{uomLabelKey(u.code) ? t(uomLabelKey(u.code)) : u.name}</SelectItem>
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

      {/* Recipient picker for free-text заявки: the backend requires ≥1 seller routing
          (NO_RECIPIENTS invariant), and typed lines imply none — so the buyer chooses here. */}
      <Dialog
        open={pickerOpen}
        onOpenChange={(open) => {
          setPickerOpen(open);
          if (!open) { setTouchedPicker(false); setSelectedSellerIds([]); }  // reopen → пере-подскажем
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t('requestItems.pickSuppliersTitle')}</DialogTitle>
            <DialogDescription>{t('requestItems.pickSuppliersDesc')}</DialogDescription>
          </DialogHeader>
          {/* R1 — подсказка: платформа сама нашла подходящих продавцов по позициям заявки. */}
          {mergedSuggested.length > 0 && (
            <div className="flex items-start gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs">
              <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              <span>{t('requestItems.suggestedHint', { count: mergedSuggested.length })}</span>
            </div>
          )}
          {/* R3 — опциональный AI-проход: покупатель дожимает подбор, когда триграм ничего
              (или мало) не нашёл — опечатки, синонимы, латиница. Явное действие, не авто. */}
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>{t('requestItems.aiSuggestHint')}</span>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 shrink-0 gap-1.5 text-xs"
              onClick={runAiSuggest}
              disabled={suggestAi.isPending}
            >
              {suggestAi.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              {t('requestItems.aiSuggestButton')}
            </Button>
          </div>
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {suppliersLoading ? (
              <p className="py-4 text-center text-sm text-muted-foreground">…</p>
            ) : (suppliers?.length ?? 0) === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">{t('requestItems.noSuppliers')}</p>
            ) : (
              orderedSuppliers.map((supplier) => {
                const hit = suggestedById.get(supplier.id);
                return (
                  <label
                    key={supplier.id}
                    className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-accent"
                  >
                    <Checkbox
                      checked={selectedSellerIds.includes(supplier.id)}
                      onCheckedChange={() => toggleSeller(supplier.id)}
                    />
                    <span className="flex-1 text-sm">{supplier.name}</span>
                    {hit ? (
                      <Badge variant="secondary" className="gap-1 text-xs font-normal">
                        <Sparkles className="h-3 w-3" aria-hidden="true" />
                        {t('requestItems.matchedLines', { matched: hit.matched_lines, total: hit.total_lines })}
                      </Badge>
                    ) : supplier.inn ? (
                      <span className="text-xs text-muted-foreground">{t('nav.inn')} {supplier.inn}</span>
                    ) : null}
                  </label>
                );
              })
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPickerOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={handleRouteAndSubmit}
              disabled={selectedSellerIds.length === 0 || routeDeal.isPending || submitRequest.isPending}
            >
              <Send className="mr-1.5 h-4 w-4" />
              {t('requestItems.sendToSelected')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
