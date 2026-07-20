import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronUp, ChevronDown, Trash2 } from 'lucide-react';
import type { QuoteItem } from '@/api/crmApi';
import { cn } from '@/lib/utils';
import { formatMoney } from '@/utils/decimal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { TableRow, TableCell } from '@/components/ui/table';
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
		selection, mainColCount, draftItems, presentationCurrency, pricingMirror,
		handleMoveRow, handleRenameRow, handleDeleteItem, rowRefs,
	} = useQuoteBuilderGrid();

	const isSection = (item.display_type ?? 'ITEM') === 'SECTION';

	// Local editing buffer so typing doesn't fire a network PATCH per keystroke — commit on blur.
	const [text, setText] = useState(item.imported_raw_name ?? '');
	// Re-sync when a server refetch replaces this row's persisted heading/text (e.g. after rename).
	useEffect(() => { setText(item.imported_raw_name ?? ''); }, [item.imported_raw_name]);

	const isRowSelected = selection.isSelected(item.id);
	const isFirst = index === 0;
	const isLast = index === draftItems.length - 1;

	// Combined ref: keep the parent's per-id map (bulk-reject scroll-into-view) AND feed the
	// virtualizer's dynamic-height measurement (a section heading can wrap to two lines).
	const setRowRef = (element: HTMLTableRowElement | null) => {
		if (element) rowRefs.current.set(item.id, element);
		else rowRefs.current.delete(item.id);
		measureElement?.(element);
	};

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
			<TableCell className={cn('w-8 px-1 py-1.5 text-center sticky left-0 z-10', stickyBg)}>
				<Checkbox
					checked={isRowSelected}
					onClick={(event) => selection.toggle(item.id, (event as React.MouseEvent).shiftKey)}
					aria-label={t('quote.bulk.selectRow', { index: index + 1 })}
				/>
			</TableCell>
			<TableCell colSpan={mainColCount - 1} className="px-2 py-1.5">
				<div className="flex items-center gap-2">
					<Input
						value={text}
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
				</div>
			</TableCell>
		</TableRow>
	);
};
