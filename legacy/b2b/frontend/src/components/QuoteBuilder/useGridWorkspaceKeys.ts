import type React from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { QuoteItem } from '@/api/crmApi';
import { serializeRowsToTsv } from './gridClipboard';
import type { UseRowSelectionResult } from './useRowSelection';

export interface GridWorkspaceKeysParams {
	/** FULL draft row set (copy-out serializes the selected rows from here). */
	draftItems: QuoteItem[];
	/** Row multi-select — copy-out reads `selectedIds`/`count`. */
	selection: UseRowSelectionResult;
	/** Local draft undo/redo stack (WP-J / U6). */
	undo: () => void;
	redo: () => void;
	canUndo: boolean;
	canRedo: boolean;
}

export interface GridWorkspaceKeysResult {
	handleWorkspaceKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => void;
}

/**
 * U6 working-area keyboard shortcuts, extracted from the QuoteBuilderGrid facade (U6 split): Ctrl/Cmd+C
 * copies the selected rows as TSV, while Ctrl/Cmd+Z · Shift+Z · Ctrl/Cmd+Y drive the local draft
 * undo/redo. Pure extraction — behavior is unchanged.
 */
export function useGridWorkspaceKeys({
	draftItems,
	selection,
	undo,
	redo,
	canUndo,
	canRedo,
}: GridWorkspaceKeysParams): GridWorkspaceKeysResult {
	const { t } = useTranslation();

	// U6 copy-out: serialize the selected rows as TSV (column order name→qty→price, so it round-trips
	// straight back through Excel-paste). Clipboard write needs the keydown user gesture; a blocked
	// clipboard (permissions / older browser) surfaces a toast instead of failing silently.
	const copySelectedRows = async () => {
		const rows = draftItems.filter((item) => selection.selectedIds.has(item.id));
		if (rows.length === 0) return;
		try {
			await navigator.clipboard.writeText(serializeRowsToTsv(rows));
			toast.success(t('quote.copy.copied', { count: rows.length }));
		} catch {
			toast.error(t('quote.copy.failed'));
		}
	};

	// Ctrl/Cmd+C copies the selected rows; Ctrl/Cmd+Z · Shift+Z · Ctrl/Cmd+Y drive the local draft
	// undo/redo. Text editing inside a cell keeps native clipboard + native Ctrl+Z (the OS owns the
	// in-input caret history), so undo/redo stay inert while a text input owns focus.
	const handleWorkspaceKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
		if (!(event.ctrlKey || event.metaKey)) return;
		const target = event.target as HTMLElement;
		const isTextInput = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
		const inEditable = isTextInput || target.tagName === 'SELECT' || target.isContentEditable;

		// Copy-out — only when rows are selected AND no editable field legitimately owns the copy.
		// Native copy wins when the user has highlighted text, OR focus sits in an editable element
		// OUTSIDE the grid (the toolbar «найти в КП» search, the Charges tab) — a stale row selection
		// must not hijack Ctrl+C there. Inside a grid cell with no text highlighted, row-copy fires.
		if ((event.key === 'c' || event.key === 'C') && !event.shiftKey && !event.altKey) {
			if (selection.count === 0) return; // nothing selected → native copy
			const inGridRow = Boolean(target.closest('[data-row-id]'));
			const hasTextHighlighted = isTextInput && target.selectionStart !== target.selectionEnd;
			if (hasTextHighlighted) return; // copying highlighted cell text
			if (inEditable && !inGridRow) return; // editable outside the grid → native copy
			event.preventDefault();
			void copySelectedRows();
			return;
		}

		if (inEditable) return; // native Ctrl+Z / Ctrl+Y owns text-input history
		if (event.key === 'z' || event.key === 'Z') {
			event.preventDefault();
			if (event.shiftKey) {
				if (canRedo) redo();
			} else if (canUndo) {
				undo();
			}
			return;
		}
		if ((event.key === 'y' || event.key === 'Y') && !event.shiftKey) {
			event.preventDefault();
			if (canRedo) redo();
		}
	};

	return { handleWorkspaceKeyDown };
}
