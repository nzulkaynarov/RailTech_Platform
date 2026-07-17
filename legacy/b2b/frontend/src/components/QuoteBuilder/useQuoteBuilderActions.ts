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
					margin_percent: item.margin_percent,
					discount_percent: item.discount_percent,
					lead_time_days: item.lead_time_days,
					hs_code: item.hs_code,
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
			await bulkCreateMutation.mutateAsync({ quoteId, items: rows as unknown as Array<Record<string, unknown>> });
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
		if (ids.length === 0) return;
		try {
			await bulkDeleteMutation.mutateAsync(ids);
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

	// Discount / price change: PURE local draft edits (one undo step each) — no network call.
	const handleBulkDiscount = (percent: number) => {
		const edits = [...selection.selectedIds].map((id) => ({
			id, field: 'discount_percent' as const, value: String(percent),
		}));
		if (edits.length === 0) return;
		applyBulk(edits);
		toast.success(t('quote.bulk.discountApplied', { count: edits.length }));
		selection.clear();
	};

	const handleBulkPriceChange = (percent: number) => {
		const factor = 1 + percent / 100;
		let clampedAny = false;
		const edits = [...selection.selectedIds].map((id) => {
			const item = draftItems.find((row) => row.id === id);
			const raw = toDecimal(item?.frozen_base_price).mul(factor);
			let next = raw;
			if (next.lessThan(0)) next = toDecimal(0);
			if (next.greaterThan(QUOTE_ITEM_MAX_UNIT_PRICE)) next = toDecimal(QUOTE_ITEM_MAX_UNIT_PRICE);
			if (!next.equals(raw)) clampedAny = true;
			return { id, field: 'frozen_base_price' as const, value: next.toDecimalPlaces(2).toString() };
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
		const items = selectedInOrder.map(
			(item) => buildDuplicatePayload(item, t('quote.bulk.copySuffix')) as unknown as Record<string, unknown>,
		);
		try {
			await bulkCreateMutation.mutateAsync({ quoteId, items });
			toast.success(t('quote.bulk.duplicated', { count: items.length }));
			selection.clear();
		} catch (error) {
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
			for (const suggestion of suggestions) {
				await updateMutation.mutateAsync({
					id: suggestion.item_id,
					// suggestion.currency is string|null; coerce null→undefined to skip overriding the line currency.
					data: { frozen_base_price: suggestion.base_price, frozen_currency: suggestion.currency ?? undefined, lead_time_days: suggestion.lead_time_days },
				});
			}
			toast.success(t('pricingAssist.applied', { count: suggestions.length }));
		} catch {
			// pricing-assist PATCHes carry NO `version` token, so the backend takes the last-write-wins
			// path and can never answer 409 QUOTE_ITEM_STALE here — there is no conflict branch to
			// handle (unlike the versioned bulk save). Any failure is a plain error toast.
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
		handleBulkDelete,
		handleBulkDiscount,
		handleBulkPriceChange,
		handleBulkDuplicate,
		handlePricingAssist,
	};
}
