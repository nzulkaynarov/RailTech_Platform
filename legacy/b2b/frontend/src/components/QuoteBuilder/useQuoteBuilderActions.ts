import type { Dispatch, SetStateAction, RefObject, MutableRefObject, ClipboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { QuoteItem, Deal, crmApi } from '@/api/crmApi';
import type {
	useUpdateQuoteItem, useBulkUpdateQuoteItems, useBulkCreateQuoteItems, useBulkDeleteQuoteItems,
	useCreateQuoteItem, useDeleteQuoteItem,
} from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';
import { toDecimal } from '@/utils/decimal';
import {
	parseBulkItemErrors, parseBulkCreateItemErrors, extractBulkErrorRows, hiddenErrorFields,
	extractStaleConflictIds,
} from './bulkErrors';
import { shouldInterceptClipboardPaste, type BulkCreateRow } from './parseClipboardTable';
import { buildDuplicatePayload } from './duplicatePayload';
import type { BulkFieldEdit } from './useQuoteDraft';
import type { UseRowSelectionResult } from './useRowSelection';
import { QUOTE_ITEM_MAX_QUANTITY, QUOTE_ITEM_MAX_UNIT_PRICE, parseAddRowNumber } from './gridConstants';

export interface QuoteBuilderActionsParams {
	dealId: number;
	deal: Deal | undefined;
	draftItems: QuoteItem[];
	dirtyIds: Set<number>;
	selection: UseRowSelectionResult;
	/** Narrow viewport gate — decides whether the cost columns count as "hidden" in a save-reject. */
	isCompact: boolean;
	// Mutations (typed exactly as the useCRM hooks return, so the payloads stay contract-checked).
	updateMutation: ReturnType<typeof useUpdateQuoteItem>;
	bulkUpdateMutation: ReturnType<typeof useBulkUpdateQuoteItems>;
	bulkCreateMutation: ReturnType<typeof useBulkCreateQuoteItems>;
	bulkDeleteMutation: ReturnType<typeof useBulkDeleteQuoteItems>;
	createItemMutation: ReturnType<typeof useCreateQuoteItem>;
	deleteItemMutation: ReturnType<typeof useDeleteQuoteItem>;
	// Draft-machine writers.
	applyBulk: (edits: BulkFieldEdit[]) => void;
	clearDirtyAfterSave: (ids: number[]) => void;
	// Add-row controlled state.
	newItemName: string;
	newItemQty: string;
	newItemPrice: string;
	deleteTarget: number | null;
	// Setters.
	setCellErrors: Dispatch<SetStateAction<Record<string, string>>>;
	setExpandedRowId: Dispatch<SetStateAction<number | null>>;
	setNewItemName: Dispatch<SetStateAction<string>>;
	setNewItemQty: Dispatch<SetStateAction<string>>;
	setNewItemPrice: Dispatch<SetStateAction<string>>;
	setPasteText: Dispatch<SetStateAction<string>>;
	setPasteRowErrors: Dispatch<SetStateAction<Record<number, Record<string, string>>>>;
	setPasteOpen: Dispatch<SetStateAction<boolean>>;
	setDeleteTarget: Dispatch<SetStateAction<number | null>>;
	setPricingBusy: Dispatch<SetStateAction<boolean>>;
	setDraftBusy: Dispatch<SetStateAction<boolean>>;
	// Optimistic-lock conflict dialog (волна 3) — a stale save opens it instead of a cell highlight.
	setConflictIds: Dispatch<SetStateAction<number[]>>;
	setConflictOpen: Dispatch<SetStateAction<boolean>>;
	// Refs.
	addNameRef: RefObject<HTMLInputElement>;
	addRowRef: RefObject<HTMLTableRowElement>;
	rowRefs: MutableRefObject<Map<number, HTMLTableRowElement>>;
	onSave?: () => void;
}

/**
 * All mutation-driven КП builder actions (save · add · Excel-paste · delete · bulk · pricing-assist ·
 * AI draft) as plain closures — extracted VERBATIM from the former monolithic grid so behaviour is
 * unchanged. They stay un-memoized (recreated per render, exactly as the inline closures were), and
 * read everything they need through the params bag the controller assembles.
 */
export function useQuoteBuilderActions(params: QuoteBuilderActionsParams) {
	const { t } = useTranslation();
	const queryClient = useQueryClient();
	const {
		dealId, deal, draftItems, dirtyIds, selection, isCompact,
		updateMutation, bulkUpdateMutation, bulkCreateMutation, bulkDeleteMutation, createItemMutation, deleteItemMutation,
		applyBulk, clearDirtyAfterSave,
		newItemName, newItemQty, newItemPrice, deleteTarget,
		setCellErrors, setExpandedRowId, setNewItemName, setNewItemQty, setNewItemPrice,
		setPasteText, setPasteRowErrors, setPasteOpen, setDeleteTarget, setPricingBusy, setDraftBusy,
		setConflictIds, setConflictOpen,
		addNameRef, addRowRef, rowRefs, onSave,
	} = params;

	// AI draft-КП (Move 3): turn the buyer request into a pre-filled draft in one click.
	const handleGenerateDraft = async () => {
		if (!dealId) return;
		setDraftBusy(true);
		try {
			const { prefilled } = await crmApi.generateDraftQuote(dealId);
			await queryClient.invalidateQueries({ queryKey: ['deals'] });
			await queryClient.invalidateQueries({ queryKey: ['quote-items'] });
			toast.success(t('aiDraft.generated', { count: prefilled }));
		} catch (e) {
			toast.error(translateApiError(e));
		} finally {
			setDraftBusy(false);
		}
	};

	const handleSave = async () => {
		// Only push rows the seller actually edited; the server refetch re-merges the rest.
		const editedItems = draftItems.filter((item) => dirtyIds.has(item.id));
		if (editedItems.length === 0) return;
		const quoteId = deal?.active_quote?.id;
		if (!quoteId) return;
		try {
			// P0-4: ONE transactional request (all-or-nothing).
			await bulkUpdateMutation.mutateAsync({
				quoteId,
				items: editedItems.map((item) => ({
					id: item.id,
					// Optimistic-lock token (волна 3): the row revision the grid last read. A stale
					// value → the server rejects the whole batch with QUOTE_ITEM_STALE (no clobber).
					version: item.version,
					quantity: item.quantity,
					frozen_base_price: item.frozen_base_price,
					frozen_currency: item.frozen_currency,
					logistics_cost: item.logistics_cost,
					customs_duty: item.customs_duty,
					// DT1 — sent VERBATIM, including an explicit `null`. `null` = «наследовать маржу
					// КП» (no per-line override); a number = an override that beats the КП margin,
					// and `0` is a REAL override meaning «продать по себестоимости». Coercing the
					// null to 0 anywhere on this path would silently reprice the line to cost, so
					// the draft machine carries null end-to-end (see `DraftFieldValue`) and JSON
					// serializes it as `null` — which the serializer accepts (allow_null=True).
					margin_percent: item.margin_percent,
					discount_percent: item.discount_percent,
					lead_time_days: item.lead_time_days,
					hs_code: item.hs_code,
					// S1: persist the optional flag toggled in the grid (draft edit → this batch).
					is_optional: item.is_optional,
				})),
			});
			setCellErrors({});
			clearDirtyAfterSave(editedItems.map((item) => item.id));
			toast.success(t('quote.save.success'));
			if (onSave) onSave();
		} catch (error) {
			// Transactional rejection → NOTHING was written; keep the dirty rows and highlight cells.
			const rows = extractBulkErrorRows(error);
			if (rows !== null) {
				// Concurrency conflict (волна 3): one or more rows were saved by a colleague since we
				// read them. This isn't a fixable input error — open the refresh dialog for those rows
				// instead of highlighting cells, so the seller consciously reloads the fresh values.
				const staleIds = extractStaleConflictIds(rows);
				if (staleIds.length > 0) {
					setConflictIds(staleIds);
					setConflictOpen(true);
					return;
				}
				const parsed = parseBulkItemErrors(rows);
				setCellErrors(parsed);
				const rowCount = new Set(Object.keys(parsed).map((key) => key.split(':')[0])).size;
				toast.error(t('quote.save.rowsWithErrors', { count: rowCount }));
				// Fast-follow (ревью #317): if the first offending cell is in a COLLAPSED detail row
				// (or a cost column hidden on a narrow screen), auto-expand + scroll it into view.
				const showCost = !!deal?.active_quote?.economics && !isCompact;
				const firstHiddenErrorId = draftItems.find(
					(item) => hiddenErrorFields(parsed, item.id, showCost).length > 0,
				)?.id;
				if (firstHiddenErrorId != null) {
					setExpandedRowId(firstHiddenErrorId);
					requestAnimationFrame(() =>
						rowRefs.current.get(firstHiddenErrorId)?.scrollIntoView?.({ block: 'center' }),
					);
				}
			} else {
				toast.error(translateApiError(error));
			}
		}
	};

	// «Добавить и продолжить» (spec §5 п.7): add the row, KEEP the add-row open, reset the fields,
	// refocus the name input, and scroll the new row into view. Enter also submits.
	const handleAddItem = async () => {
		if (!newItemName.trim() || !deal?.active_quote) return;
		const qty = Math.min(QUOTE_ITEM_MAX_QUANTITY, Math.max(1, Math.trunc(parseAddRowNumber(newItemQty) || 1)));
		const price = Math.min(QUOTE_ITEM_MAX_UNIT_PRICE, Math.max(0, parseAddRowNumber(newItemPrice) || 0));
		try {
			await createItemMutation.mutateAsync({
				quote: deal.active_quote.id,
				imported_raw_name: newItemName.trim(),
				quantity: qty,
				frozen_base_price: String(price),
				// New lines inherit the КП's default cost currency (fallback UZS).
				frozen_currency: deal.active_quote.cost_currency_default || 'UZS',
			});
			setNewItemName('');
			setNewItemQty('1');
			setNewItemPrice('0');
			// Keep the add-row open and put the cursor back in the name field for the next line.
			// DT9: focus SYNCHRONOUSLY first. The await above resolves after the mutation's cache
			// invalidation, so React re-renders the whole grid; by the time the rAF callback ran, focus
			// had already been dropped to <body> and Enter on the last add-row felt like it "lost" the
			// cursor. The rAF pass stays as the belt-and-braces re-focus after that re-render commits.
			addNameRef.current?.focus();
			requestAnimationFrame(() => {
				addNameRef.current?.focus();
				addRowRef.current?.scrollIntoView?.({ block: 'nearest' });
			});
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	};

	// Excel-paste entry (a): the toolbar button pre-fills the dialog from the clipboard when granted.
	const openPasteDialog = async () => {
		let clipboard = '';
		try {
			clipboard = await navigator.clipboard.readText();
		} catch {
			// No clipboard-read permission — the dialog textarea accepts a manual paste instead.
		}
		setPasteText(clipboard);
		setPasteRowErrors({});
		setPasteOpen(true);
	};

	// Excel-paste entry (b): a native paste on the grid. Single-cell paste into an input falls through;
	// multi-line/tab-separated tabular text is hijacked into the preview dialog. Frozen КП → ignored.
	const handleGridPaste = (event: ClipboardEvent<HTMLDivElement>) => {
		if (deal?.active_quote?.frozen_at) return;
		const text = event.clipboardData.getData('text/plain');
		const target = event.target as HTMLElement | null;
		const targetIsEditable = !!target
			&& (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target.isContentEditable);
		if (!shouldInterceptClipboardPaste(text, targetIsEditable)) return;
		event.preventDefault();
		setPasteText(text);
		setPasteRowErrors({});
		setPasteOpen(true);
	};

	// Confirm: ONE transactional bulk-create. A rejected batch keeps the dialog open + highlights rows.
	const handlePasteConfirm = async (rows: BulkCreateRow[]) => {
		const quoteId = deal?.active_quote?.id;
		if (!quoteId || rows.length === 0) return;
		try {
			// DT6: `BulkCreateRow` is a type ALIAS (not an interface), so it is structurally assignable to
			// `Record<string, unknown>` — no `as unknown as` escape hatch, the payload stays type-checked.
			await bulkCreateMutation.mutateAsync({ quoteId, items: rows });
			toast.success(t('quote.paste.added', { count: rows.length }));
			setPasteOpen(false);
			setPasteRowErrors({});
		} catch (error) {
			const errorRows = extractBulkErrorRows(error);
			if (errorRows) {
				setPasteRowErrors(parseBulkCreateItemErrors(errorRows));
			} else {
				toast.error(translateApiError(error));
			}
		}
	};

	const handleDeleteItem = (id: number) => {
		setDeleteTarget(id);
	};

	const confirmDeleteItem = async () => {
		if (deleteTarget == null) return;
		try {
			await deleteItemMutation.mutateAsync(deleteTarget);
			setDeleteTarget(null);
		} catch {
			toast.error(t('errors.operationFailed'));
			setDeleteTarget(null);
		}
	};

	// ── WP-J bulk actions over the selected rows ──────────────────────────────────────────
	const handleBulkDelete = async () => {
		const ids = [...selection.selectedIds];
		const quoteId = deal?.active_quote?.id;
		if (ids.length === 0 || !quoteId) return;
		try {
			await bulkDeleteMutation.mutateAsync({ quoteId, ids });
			setCellErrors((previous) => {
				const next = { ...previous };
				for (const key of Object.keys(next)) {
					if (ids.includes(Number(key.split(':')[0]))) delete next[key];
				}
				return next;
			});
			selection.clear();
			toast.success(t('quote.bulk.deleted', { count: ids.length }));
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	};

	// Discount / price change: PURE local draft edits (one undo step each) — no network call. S1:
	// only ITEM rows carry pricing, so a selected SECTION/NOTE is skipped (a priced group header
	// would fail the backend SECTION_NOTE_NO_PRICING guard on save).
	const handleBulkDiscount = (percent: number) => {
		const edits = draftItems
			.filter((row) => selection.selectedIds.has(row.id) && (row.display_type ?? 'ITEM') === 'ITEM')
			.map((row) => ({ id: row.id, field: 'discount_percent' as const, value: String(percent) }));
		if (edits.length === 0) return;
		applyBulk(edits);
		toast.success(t('quote.bulk.discountApplied', { count: edits.length }));
		selection.clear();
	};

	const handleBulkPriceChange = (percent: number) => {
		const factor = 1 + percent / 100;
		let clampedAny = false;
		// S1: only ITEM rows carry a base price — a selected SECTION/NOTE is skipped.
		const edits = draftItems
			.filter((row) => selection.selectedIds.has(row.id) && (row.display_type ?? 'ITEM') === 'ITEM')
			.map((item) => {
				const raw = toDecimal(item.frozen_base_price).mul(factor);
				let next = raw;
				if (next.lessThan(0)) next = toDecimal(0);
				if (next.greaterThan(QUOTE_ITEM_MAX_UNIT_PRICE)) next = toDecimal(QUOTE_ITEM_MAX_UNIT_PRICE);
				if (!next.equals(raw)) clampedAny = true;
				return { id: item.id, field: 'frozen_base_price' as const, value: next.toDecimalPlaces(2).toString() };
			});
		if (edits.length === 0) return;
		applyBulk(edits);
		// Warn (not silently) when any row's computed price hit the 0..cap bounds.
		if (clampedAny) toast.warning(t('quote.validation.valueClamped'));
		toast.success(t('quote.bulk.priceApplied', { count: edits.length }));
		selection.clear();
	};

	// Duplicate: build a bulk-create payload from the CURRENT draft values of the selected rows.
	const handleBulkDuplicate = async () => {
		const quoteId = deal?.active_quote?.id;
		if (!quoteId) return;
		const selectedInOrder = draftItems.filter((item) => selection.selectedIds.has(item.id));
		if (selectedInOrder.length === 0) return;
		// DT6: same as the paste path — `DuplicateItemPayload` is a type alias, so it satisfies the
		// bulk-create row contract structurally. No cast.
		const items = selectedInOrder.map((item) => buildDuplicatePayload(item, t('quote.bulk.copySuffix')));
		try {
			await bulkCreateMutation.mutateAsync({ quoteId, items });
			toast.success(t('quote.bulk.duplicated', { count: items.length }));
			selection.clear();
		} catch (error) {
			toast.error(translateApiError(error));
		}
	};

	// ── S1: секции / заметки / перемещение (спека §5 п.19) ────────────────────────────────
	// «+ Секция» / «+ Заметка»: create a SECTION/NOTE row via the single-item create endpoint.
	// imported_raw_name is the heading/text (editable inline afterwards); NO pricing is sent (the
	// backend validate() rejects a priced SECTION/NOTE — SECTION_NOTE_NO_PRICING). The row lands at
	// the END of the КП (perform_create backfills position = max+1).
	const handleAddSectionOrNote = async (displayType: 'SECTION' | 'NOTE') => {
		const quote = deal?.active_quote;
		if (!quote) return;
		try {
			await createItemMutation.mutateAsync({
				quote: quote.id,
				imported_raw_name: displayType === 'SECTION' ? t('quote.section.newTitle') : t('quote.note.newText'),
				display_type: displayType,
			});
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	};
	const handleAddSection = () => handleAddSectionOrNote('SECTION');
	const handleAddNote = () => handleAddSectionOrNote('NOTE');

	// Rename a row inline: a SECTION heading / NOTE text, or (U3) an ITEM's free-typed name.
	// bulk-update can NOT write imported_raw_name, so this goes through the single-item PATCH (full
	// serializer). Empty title → ignored (keep the previous, never persist a blank name). Fires on blur.
	const handleRenameRow = async (id: number, value: string) => {
		const trimmed = value.trim();
		if (!trimmed) return;
		// U3 + the handleMoveRow guard, same root cause: `perform_update` BUMPS the row's server
		// version, but a dirty row keeps its local draft (with the OLD version) across the refetch —
		// so renaming a row that has unsaved field edits would make the next Save false-409
		// (QUOTE_ITEM_STALE) and the conflict reload would throw those edits away. SECTION/NOTE rows
		// carry no editable pricing fields and are never dirty, so this only ever fires for U3's
		// ITEM-name path. Ask to save first rather than silently losing work.
		if (dirtyIds.has(id)) {
			toast.warning(t('quote.row.saveBeforeRename'));
			return;
		}
		try {
			await updateMutation.mutateAsync({ id, data: { imported_raw_name: trimmed } });
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	};

	// Move a row one slot ↑/↓ by SWAPPING its `position` with the adjacent row via the transactional
	// bulk-update (both rows in one payload) — NOT drag (which fights the virtualizer + sticky
	// columns). draftItems is already position-sorted (server ordering), so the neighbour is the
	// adjacent index. Positions are distinct after the backfill/bulk-create sequential assignment; a
	// legacy collision falls back to the visible indices so the swap always yields two different
	// positions. A stale row (colleague reordered first) opens the same conflict dialog as Save.
	const handleMoveRow = async (id: number, direction: 'up' | 'down') => {
		const quoteId = deal?.active_quote?.id;
		if (!quoteId) return;
		const index = draftItems.findIndex((row) => row.id === id);
		if (index === -1) return;
		const swapIndex = direction === 'up' ? index - 1 : index + 1;
		if (swapIndex < 0 || swapIndex >= draftItems.length) return;
		const moving = draftItems[index];
		const neighbour = draftItems[swapIndex];
		// The swap bulk-update bumps BOTH rows' server version. If a moved row has unsaved field
		// edits, its draft keeps the old version → the next Save would false-409 (QUOTE_ITEM_STALE)
		// and the reload would discard the edit. Only the two rows in THIS swap matter, so a targeted
		// guard (not a blanket hasUnsavedChanges block) — ask to save just those first.
		if (dirtyIds.has(moving.id) || dirtyIds.has(neighbour.id)) {
			toast.warning(t('quote.row.saveBeforeMove'));
			return;
		}
		let movingPosition = neighbour.position;
		let neighbourPosition = moving.position;
		if (moving.position == null || neighbour.position == null || moving.position === neighbour.position) {
			movingPosition = swapIndex;
			neighbourPosition = index;
		}
		try {
			await bulkUpdateMutation.mutateAsync({
				quoteId,
				items: [
					{ id: moving.id, position: movingPosition, version: moving.version },
					{ id: neighbour.id, position: neighbourPosition, version: neighbour.version },
				],
			});
		} catch (error) {
			const rows = extractBulkErrorRows(error);
			if (rows !== null) {
				const staleIds = extractStaleConflictIds(rows);
				if (staleIds.length > 0) {
					setConflictIds(staleIds);
					setConflictOpen(true);
					return;
				}
			}
			toast.error(translateApiError(error));
		}
	};

	// Pricing-assist (Move 3): pull line costs from the seller's own SupplierOffers and prefill.
	const handlePricingAssist = async () => {
		const activeQuote = deal?.active_quote;
		if (!activeQuote) return;
		setPricingBusy(true);
		try {
			const { suggestions } = await crmApi.pricingAssist(activeQuote.id);
			if (!suggestions.length) {
				toast.info(t('pricingAssist.none'));
				return;
			}
			// DT4: ONE transactional bulk-update instead of N sequential PATCHes. The old loop fired N
			// requests, each invalidating quote-items + deals — so the grid refetched and flickered N
			// times, and a mid-loop failure left the КП half-applied. `version` is deliberately OMITTED
			// (it is optional on the bulk endpoint, crm/services/quotes/bulk.py), which keeps the exact
			// last-write-wins semantics the per-row PATCHes had: pricing-assist can still never answer
			// 409 QUOTE_ITEM_STALE, so there is no conflict branch to handle here.
			await bulkUpdateMutation.mutateAsync({
				quoteId: activeQuote.id,
				items: suggestions.map((suggestion) => ({
					id: suggestion.item_id,
					frozen_base_price: suggestion.base_price,
					// suggestion.currency is string|null; coerce null→undefined to skip overriding the line currency.
					frozen_currency: suggestion.currency ?? undefined,
					lead_time_days: suggestion.lead_time_days,
				})),
			});
			toast.success(t('pricingAssist.applied', { count: suggestions.length }));
		} catch {
			// Transactional: a rejected batch wrote NOTHING, so there is no partial state to unwind.
			toast.error(t('pricingAssist.error'));
		} finally {
			setPricingBusy(false);
		}
	};

	return {
		handleGenerateDraft,
		handleSave,
		handleAddItem,
		openPasteDialog,
		handleGridPaste,
		handlePasteConfirm,
		handleDeleteItem,
		confirmDeleteItem,
		handleAddSection,
		handleAddNote,
		handleRenameRow,
		handleMoveRow,
		handleBulkDelete,
		handleBulkDiscount,
		handleBulkPriceChange,
		handleBulkDuplicate,
		handlePricingAssist,
	};
}
