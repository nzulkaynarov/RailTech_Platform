import React, { useCallback } from 'react';
import { useDraftState } from '@/hooks/useDraftState';
import { useTranslation } from 'react-i18next';
import { ChevronUp, ChevronDown, ChevronRight, Trash2 } from 'lucide-react';
import type { QuoteItem } from '@/api/crmApi';
import { cn } from '@/lib/utils';
import { formatMoney } from '@/utils/decimal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TableRow, TableCell } from '@/components/ui/table';
import { RowSelectCheckbox } from './RowSelectCheckbox';
import { useQuoteBuilderGrid } from './QuoteBuilderGridContext';

interface SectionNoteRowProps {
	item: QuoteItem;
	/** 0-based row index in the visible (draftItems) order — drives the selection aria-label and the
	 *  first/last guard for the ↑/↓ buttons. */
	index: number;
	/** Virtualizer index for `data-index` (windowed rendering only). */
	virtualIndex?: number;
	/** Virtualizer's dynamic-height measure callback (windowed rendering only) — a SECTION/NOTE is a
	 *  variable-height full-width row, so it must be measured like an ITEM row. */
	measureElement?: (node: Element | null) => void;
}

/**
 * S1 (спека §5 п.19) — a full-width КП row for a SECTION (group heading) or a NOTE (free-text).
 * Neither carries a price: SECTION renders a bold, editable heading plus a LIVE подытог (Σ billable
 * rows under it, from usePricingMirror); NOTE renders an editable italic line. Both offer move ↑/↓
 * (swap position via bulk-update) and delete, and are keyboard-navigable via their own inputs — they
 * carry NO `data-cell-col`, so the Excel-style column navigation skips over them automatically.
 */
export const SectionNoteRow: React.FC<SectionNoteRowProps> = ({ item, index, virtualIndex, measureElement }) => {
	const { t } = useTranslation();
	const {
		readOnly, selection, mainColCount, draftItems, presentationCurrency, pricingMirror,
		handleMoveRow, handleRenameRow, handleDeleteItem, rowRefs,
		isSectionCollapsed, toggleSectionCollapse, itemsUnderSection, rowPaddingY,
	} = useQuoteBuilderGrid();

	const isSection = (item.display_type ?? 'ITEM') === 'SECTION';
	// U5: a collapsed SECTION hides its children from the visible list (they leave the virtualizer +
	// keyboard nav entirely) and surfaces their Σ on the heading itself. A NOTE that belongs to a
	// section is left-indented to read as part of the group (same cue as its ITEM siblings).
	const isCollapsed = isSection && isSectionCollapsed(item.id);
	const isNoteUnderSection = !isSection && itemsUnderSection.has(item.id);

	// Local editing buffer so typing doesn't fire a network PATCH per keystroke — commit on blur.
	// Пересобирается, когда сервер вернул другой текст строки (например, после переименования):
	// корректировка в рендере, а не эффект — иначе кадр со старым текстом.
	const [text, setText] = useDraftState(item.imported_raw_name ?? '', (value: string) => value);

	const isRowSelected = selection.isSelected(item.id);
	const isFirst = index === 0;
	const isLast = index === draftItems.length - 1;

	// Combined ref: keep the parent's per-id map (bulk-reject scroll-into-view) AND feed the
	// virtualizer's dynamic-height measurement (a section heading can wrap to two lines).
	// B3: stable (useCallback) — a fresh arrow per render re-attaches the ref, which unobserves and
	// re-observes the node in the virtualizer's ResizeObserver and snaps the scroll window to the top.
	const setRowRef = useCallback((element: HTMLTableRowElement | null) => {
		if (element) rowRefs.current.set(item.id, element);
		else rowRefs.current.delete(item.id);
		measureElement?.(element);
	}, [item.id, measureElement, rowRefs]);

	// Commit the rename on blur — only when non-empty AND changed; a blank heading is reverted, never
	// persisted (bulk-update can't write the name, so this goes through the single-item PATCH).
	const commitRename = () => {
		const trimmed = text.trim();
		if (!trimmed) {
			setText(item.imported_raw_name ?? '');
			return;
		}
		if (trimmed !== (item.imported_raw_name ?? '').trim()) handleRenameRow(item.id, trimmed);
	};

	const sectionSubtotal = isSection ? pricingMirror.sectionSubtotalFor(item.id) : null;
	const stickyBg = isRowSelected ? 'bg-primary/10' : 'bg-background';

	return (
		<TableRow
			ref={setRowRef}
			data-row-id={item.id}
			data-index={virtualIndex}
			data-display-type={item.display_type ?? 'ITEM'}
			className={cn(
				'group transition-colors hover:bg-muted/50 focus-within:bg-muted/40',
				isSection ? 'bg-muted/40' : 'bg-background',
				isRowSelected && 'bg-primary/5',
			)}
		>
			<TableCell className={cn('w-8 px-1 text-center sticky left-0 z-10', rowPaddingY, stickyBg)}>
				<RowSelectCheckbox
					checked={isRowSelected}
					onToggle={(shiftKey) => selection.toggle(item.id, shiftKey)}
					ariaLabel={t('quote.bulk.selectRow', { index: index + 1 })}
				/>
			</TableCell>
			<TableCell colSpan={mainColCount - 1} className={cn('px-2', rowPaddingY)}>
				<div className={cn('flex items-center gap-2', isNoteUnderSection && 'ml-1 border-l-2 border-border/60 pl-3')}>
					{isSection && (
						<button
							type="button"
							onClick={() => toggleSectionCollapse(item.id)}
							aria-expanded={!isCollapsed}
							aria-label={isCollapsed ? t('quote.section.expand') : t('quote.section.collapse')}
							className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
						>
							{isCollapsed ? <ChevronRight className="size-3.5" /> : <ChevronDown className="size-3.5" />}
						</button>
					)}
					<Input
						value={text}
						readOnly={readOnly}
						onChange={(event) => setText(event.target.value)}
						onBlur={commitRename}
						onKeyDown={(event) => {
							if (event.key === 'Enter') {
								event.preventDefault();
								(event.target as HTMLInputElement).blur();
							}
						}}
						placeholder={isSection ? t('quote.section.placeholder') : t('quote.note.placeholder')}
						aria-label={isSection ? t('quote.section.aria') : t('quote.note.aria')}
						className={cn(
							'h-8 flex-1 border-none bg-transparent shadow-none focus-visible:ring-1 focus-visible:ring-ring',
							isSection ? 'text-sm font-bold uppercase tracking-wide' : 'text-xs italic text-muted-foreground',
						)}
					/>
					{isSection && sectionSubtotal != null && (
						<span className="shrink-0 whitespace-nowrap text-xs text-muted-foreground">
							{t('quote.section.subtotal')}:{' '}
							<span className="font-semibold tabular-nums text-foreground">
								{formatMoney(sectionSubtotal, presentationCurrency)}
							</span>
						</span>
					)}
					{!readOnly && (
					<div className="flex shrink-0 items-center">
						<Button
							variant="ghost"
							size="icon-xs"
							disabled={isFirst}
							onClick={() => handleMoveRow(item.id, 'up')}
							title={t('quote.row.moveUp')}
							aria-label={t('quote.row.moveUp')}
						>
							<ChevronUp className="size-3.5" />
						</Button>
						<Button
							variant="ghost"
							size="icon-xs"
							disabled={isLast}
							onClick={() => handleMoveRow(item.id, 'down')}
							title={t('quote.row.moveDown')}
							aria-label={t('quote.row.moveDown')}
						>
							<ChevronDown className="size-3.5" />
						</Button>
						<Button
							variant="ghost"
							size="icon-xs"
							onClick={() => handleDeleteItem(item.id)}
							className="text-muted-foreground hover:text-destructive"
							title={t('common.delete')}
							aria-label={t('common.delete')}
						>
							<Trash2 className="size-3" />
						</Button>
					</div>
					)}
				</div>
			</TableCell>
		</TableRow>
	);
};
