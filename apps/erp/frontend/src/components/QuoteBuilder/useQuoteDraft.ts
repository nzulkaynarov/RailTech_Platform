import { useLatestRef } from '@/hooks/useLatestRef';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { QuoteItem } from '@/api/crmApi';

/**
 * A single field edit — the unit `applyBulk` applies across many rows in one undoable step.
 *
 * DT1: `null` is a FIRST-CLASS value here, not an "unset". `margin_percent = null` means «нет
 * позиционного переопределения, наследовать маржу КП», which is semantically different from `'0'`
 * («продать по себестоимости»). The draft machine must therefore be able to hold and replay a
 * null — writing it as `''`/`0` would silently reprice the line.
 */
export type DraftFieldValue = string | number | boolean | null;

export interface BulkFieldEdit {
	id: number;
	field: keyof QuoteItem;
	value: DraftFieldValue;
}

export interface UseQuoteDraftResult {
	/** The rows the grid renders: server rows with per-row local overrides on dirty rows. */
	draftItems: QuoteItem[];
	/** Ids of rows carrying unsaved local edits. */
	dirtyIds: Set<number>;
	/** Derived from `dirtyIds` — replaces the old JSON.stringify(localItems) diff. */
	hasUnsavedChanges: boolean;
	/** Apply a single field edit to one row and mark it dirty (one undo step). */
	setField: (id: number, field: keyof QuoteItem, value: DraftFieldValue) => void;
	/** Apply many field edits across rows as ONE dirty-making, ONE-undo-step op (bulk price/discount). */
	applyBulk: (edits: BulkFieldEdit[]) => void;
	/** Discard a row's local edits — restore its last server value. */
	resetRow: (id: number) => void;
	/** After a successful save, drop these ids from the dirty set so server data can re-merge. */
	clearDirtyAfterSave: (ids: number[]) => void;
	/** Revert the last local draft edit (setField / applyBulk). No-op when the stack is empty. */
	undo: () => void;
	/** True when there is at least one draft edit to undo. */
	canUndo: boolean;
	/** Re-apply the last undone edit (symmetric with undo). No-op when the redo stack is empty. */
	redo: () => void;
	/** True when there is at least one undone edit to re-apply. */
	canRedo: boolean;
}

// Excel-like undo depth for local cell edits — enough to unwind a run of fat-finger fixes
// without holding an unbounded history in memory.
const UNDO_DEPTH = 20;

interface DraftSnapshot {
	items: QuoteItem[];
	dirty: Set<number>;
}

/**
 * Draft state machine for the КП line grid (WP-D / spec §2 P0-3, extended in WP-J).
 *
 * The old grid mirrored `quoteItems` into local state with an UNCONDITIONAL
 * `useEffect(() => setLocalItems(quoteItems), [quoteItems])`, so ANY refetch of
 * the `['quote-items']` query (fired by settings/charges/basis mutations) wiped
 * in-progress edits. Here server data merges into NON-dirty rows only; a row the
 * user is editing keeps its local values until it is saved (`clearDirtyAfterSave`)
 * or explicitly reverted (`resetRow`). Row additions/deletions still flow through
 * the server list (they change the set of rows, never a dirty row's fields).
 *
 * WP-J adds a local undo stack over the PURELY LOCAL draft edits (`setField`,
 * `applyBulk`). Network deletes/duplicates are NOT undoable here — they change the
 * server row set, which clears the stack (a snapshot references a stale row set).
 */
export function useQuoteDraft(serverItems: QuoteItem[]): UseQuoteDraftResult {
	const [draftItems, setDraftItems] = useState<QuoteItem[]>(serverItems);
	const [dirtyIds, setDirtyIds] = useState<Set<number>>(() => new Set());
	const [undoStack, setUndoStack] = useState<DraftSnapshot[]>([]);
	// Redo holds states the seller has UNDONE, so redo() can walk forward again. A fresh edit discards
	// this future (standard editor semantics — see pushUndoSnapshot).
	const [redoStack, setRedoStack] = useState<DraftSnapshot[]>([]);

	// Зеркала последнего значения, чтобы апдейтеры состояния снимали снимок «до правки», не
	// пересоздавая колбэки на каждый рендер. draftItems/dirtyIds на каждой правке ЗАМЕНЯЮТСЯ
	// (не мутируются), поэтому держать ссылку — корректный неизменяемый снимок.
	// Запись идёт после коммита (`useLatestRef`), а не в рендере: рендер обязан быть чистым.
	// Все чтения ниже — из колбэков и апдейтеров, то есть уже после коммита.
	const draftItemsRef = useLatestRef(draftItems);
	const dirtyIdsRef = useLatestRef(dirtyIds);
	const undoStackRef = useLatestRef(undoStack);
	const redoStackRef = useLatestRef(redoStack);
	const serverItemsRef = useLatestRef(serverItems);

	// A snapshot captures a row set + dirty flags; restoring it rebuilds CLEAN rows from CURRENT
	// server truth and overlays ONLY the snapshot's dirty rows. Replaying snapshot.items wholesale
	// would silently roll clean rows back to pre-refetch values (adversarial-review MAJOR) — the exact
	// stale-display bug the draft machine exists to prevent. Shared by undo and redo so both are safe.
	const restoreSnapshot = useCallback((snapshot: DraftSnapshot) => {
		const snapshotById = new Map(snapshot.items.map((item) => [item.id, item]));
		setDraftItems(
			serverItemsRef.current.map((serverItem) =>
				snapshot.dirty.has(serverItem.id) ? (snapshotById.get(serverItem.id) ?? serverItem) : serverItem,
			),
		);
		setDirtyIds(snapshot.dirty);
	}, [serverItemsRef]);

	// Push the CURRENT draft state onto the undo stack (bounded to UNDO_DEPTH) before an edit. A fresh
	// edit also invalidates the redo future — you cannot redo past a branch you just diverged from.
	const pushUndoSnapshot = useCallback(() => {
		setUndoStack((previous) => {
			const next = [...previous, { items: draftItemsRef.current, dirty: dirtyIdsRef.current }];
			if (next.length > UNDO_DEPTH) next.shift();
			return next;
		});
		setRedoStack([]);
	}, [draftItemsRef, dirtyIdsRef]);

	// Re-derive the draft from the authoritative server list whenever it changes,
	// preserving local values on rows that are still dirty. Runs on every server
	// refetch — but never overwrites a row the user is actively editing.
	useEffect(() => {
		// A row deleted server-side (own trash action or a teammate) must also leave
		// the dirty set, or hasUnsavedChanges sticks forever with nothing to save.
		const serverIds = new Set(serverItems.map((item) => item.id));
		// eslint-disable-next-line react-hooks/set-state-in-effect -- зеркало серверных строк в черновик билдера КП: долг 2.3c (объединение draft-машины), волна с прогоном глазами
		setDirtyIds((previous) => {
			const next = new Set([...previous].filter((id) => serverIds.has(id)));
			return next.size === previous.size ? previous : next;
		});
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

	// The undo snapshots reference a specific row set; a change to the server row set (add /
	// delete / duplicate) invalidates them, so clear the stack. Field-only refetches (settings /
	// charges / basis) keep the same ids, so undo survives those — exactly the local edits it owns.
	const serverIdsKey = serverItems.map((item) => item.id).join(',');
	const previousServerIdsKeyRef = useRef<string | null>(null);
	useEffect(() => {
		if (previousServerIdsKeyRef.current !== null && previousServerIdsKeyRef.current !== serverIdsKey) {
			setUndoStack([]);
			setRedoStack([]);
		}
		previousServerIdsKeyRef.current = serverIdsKey;
	}, [serverIdsKey]);

	const setField = useCallback(
		(id: number, field: keyof QuoteItem, value: DraftFieldValue) => {
			pushUndoSnapshot();
			setDraftItems((previousDraft) =>
				previousDraft.map((item) => (item.id === id ? { ...item, [field]: value } : item)),
			);
			setDirtyIds((previous) => {
				if (previous.has(id)) return previous;
				const next = new Set(previous);
				next.add(id);
				return next;
			});
		},
		[pushUndoSnapshot],
	);

	const applyBulk = useCallback(
		(edits: BulkFieldEdit[]) => {
			if (edits.length === 0) return;
			pushUndoSnapshot();
			// Group edits by row so a row touched by several fields is patched once.
			const editsById = new Map<number, Partial<QuoteItem>>();
			for (const edit of edits) {
				const patch = editsById.get(edit.id) ?? {};
				(patch as Record<string, DraftFieldValue>)[edit.field as string] = edit.value;
				editsById.set(edit.id, patch);
			}
			setDraftItems((previousDraft) =>
				previousDraft.map((item) => {
					const patch = editsById.get(item.id);
					return patch ? { ...item, ...patch } : item;
				}),
			);
			setDirtyIds((previous) => {
				const next = new Set(previous);
				for (const id of editsById.keys()) next.add(id);
				return next;
			});
		},
		[pushUndoSnapshot],
	);

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
		// The saved values are now the server baseline — old snapshots would restore pre-save
		// draft values, which is confusing after a successful save. Drop the local history.
		setUndoStack([]);
		setRedoStack([]);
	}, []);

	const undo = useCallback(() => {
		const stack = undoStackRef.current;
		if (stack.length === 0) return;
		const snapshot = stack[stack.length - 1];
		// Bank the CURRENT state onto the redo stack so redo() can walk forward again, then restore.
		setRedoStack((previous) => [...previous, { items: draftItemsRef.current, dirty: dirtyIdsRef.current }]);
		restoreSnapshot(snapshot);
		setUndoStack(stack.slice(0, -1));
	}, [restoreSnapshot, undoStackRef, draftItemsRef, dirtyIdsRef]);

	const redo = useCallback(() => {
		const stack = redoStackRef.current;
		if (stack.length === 0) return;
		const snapshot = stack[stack.length - 1];
		// Symmetric with undo: bank the current state back onto the undo stack, then re-apply.
		setUndoStack((previous) => [...previous, { items: draftItemsRef.current, dirty: dirtyIdsRef.current }]);
		restoreSnapshot(snapshot);
		setRedoStack(stack.slice(0, -1));
	}, [restoreSnapshot, redoStackRef, draftItemsRef, dirtyIdsRef]);

	const hasUnsavedChanges = dirtyIds.size > 0;
	const canUndo = undoStack.length > 0;
	const canRedo = redoStack.length > 0;

	return useMemo(
		() => ({
			draftItems,
			dirtyIds,
			hasUnsavedChanges,
			setField,
			applyBulk,
			resetRow,
			clearDirtyAfterSave,
			undo,
			canUndo,
			redo,
			canRedo,
		}),
		[draftItems, dirtyIds, hasUnsavedChanges, setField, applyBulk, resetRow, clearDirtyAfterSave, undo, canUndo, redo, canRedo],
	);
}
