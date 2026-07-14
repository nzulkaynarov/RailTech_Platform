import { useCallback, useEffect, useMemo, useState } from 'react';
import type { QuoteItem } from '@/api/crmApi';

export interface UseQuoteDraftResult {
	/** The rows the grid renders: server rows with per-row local overrides on dirty rows. */
	draftItems: QuoteItem[];
	/** Ids of rows carrying unsaved local edits. */
	dirtyIds: Set<number>;
	/** Derived from `dirtyIds` — replaces the old JSON.stringify(localItems) diff. */
	hasUnsavedChanges: boolean;
	/** Apply a single field edit to one row and mark it dirty. */
	setField: (id: number, field: keyof QuoteItem, value: string | number) => void;
	/** Discard a row's local edits — restore its last server value. */
	resetRow: (id: number) => void;
	/** After a successful save, drop these ids from the dirty set so server data can re-merge. */
	clearDirtyAfterSave: (ids: number[]) => void;
}

/**
 * Draft state machine for the КП line grid (WP-D / spec §2 P0-3).
 *
 * The old grid mirrored `quoteItems` into local state with an UNCONDITIONAL
 * `useEffect(() => setLocalItems(quoteItems), [quoteItems])`, so ANY refetch of
 * the `['quote-items']` query (fired by settings/charges/basis mutations) wiped
 * in-progress edits. Here server data merges into NON-dirty rows only; a row the
 * user is editing keeps its local values until it is saved (`clearDirtyAfterSave`)
 * or explicitly reverted (`resetRow`). Row additions/deletions still flow through
 * the server list (they change the set of rows, never a dirty row's fields).
 */
export function useQuoteDraft(serverItems: QuoteItem[]): UseQuoteDraftResult {
	const [draftItems, setDraftItems] = useState<QuoteItem[]>(serverItems);
	const [dirtyIds, setDirtyIds] = useState<Set<number>>(() => new Set());

	// Re-derive the draft from the authoritative server list whenever it changes,
	// preserving local values on rows that are still dirty. Runs on every server
	// refetch — but never overwrites a row the user is actively editing.
	useEffect(() => {
		setDraftItems((previousDraft) => {
			const previousById = new Map(previousDraft.map((item) => [item.id, item]));
			return serverItems.map((serverItem) => {
				if (dirtyIds.has(serverItem.id)) {
					// Dirty → keep the local copy (fall back to server if we somehow lost it).
					return previousById.get(serverItem.id) ?? serverItem;
				}
				return serverItem;
			});
		});
	}, [serverItems, dirtyIds]);

	const setField = useCallback((id: number, field: keyof QuoteItem, value: string | number) => {
		setDraftItems((previousDraft) =>
			previousDraft.map((item) => (item.id === id ? { ...item, [field]: value } : item)),
		);
		setDirtyIds((previous) => {
			if (previous.has(id)) return previous;
			const next = new Set(previous);
			next.add(id);
			return next;
		});
	}, []);

	const resetRow = useCallback(
		(id: number) => {
			const serverRow = serverItems.find((item) => item.id === id);
			if (serverRow) {
				setDraftItems((previousDraft) =>
					previousDraft.map((item) => (item.id === id ? serverRow : item)),
				);
			}
			setDirtyIds((previous) => {
				if (!previous.has(id)) return previous;
				const next = new Set(previous);
				next.delete(id);
				return next;
			});
		},
		[serverItems],
	);

	const clearDirtyAfterSave = useCallback((ids: number[]) => {
		setDirtyIds((previous) => {
			if (ids.length === 0) return previous;
			const next = new Set(previous);
			for (const id of ids) next.delete(id);
			return next;
		});
	}, []);

	const hasUnsavedChanges = dirtyIds.size > 0;

	return useMemo(
		() => ({ draftItems, dirtyIds, hasUnsavedChanges, setField, resetRow, clearDirtyAfterSave }),
		[draftItems, dirtyIds, hasUnsavedChanges, setField, resetRow, clearDirtyAfterSave],
	);
}
