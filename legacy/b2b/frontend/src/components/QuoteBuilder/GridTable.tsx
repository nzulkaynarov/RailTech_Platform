import React from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip';
import type { QuoteItem } from '@/api/crmApi';
import { GridRow } from './GridRow';
import { SectionNoteRow } from './SectionNoteRow';
import { useQuoteBuilderGrid } from './QuoteBuilderGridContext';

/** Route a КП line to its renderer by display_type: SECTION/NOTE → full-width SectionNoteRow,
 *  everything else (ITEM / legacy undefined) → the priced GridRow. */
const renderGridRow = (
	item: QuoteItem,
	/** 0-based index in the FULL document — the row number, the ↑/↓ first/last guard, aria-labels. */
	documentIndex: number,
	/**
	 * U4: 0-based index in the VISIBLE (filtered) list — what the virtualizer windows by. Equal to
	 * `documentIndex` when no filter is active; `undefined` when the table is not windowed.
	 */
	windowIndex: number | undefined,
	measureElement: (node: Element | null) => void,
	resizeItem: (index: number, size: number) => void,
) => {
	const windowed = windowIndex !== undefined;
	const windowProps = windowed ? { virtualIndex: windowIndex, measureElement } : {};
	return (item.display_type ?? 'ITEM') === 'ITEM'
		? <GridRow key={item.id} item={item} index={documentIndex} {...windowProps} resizeItem={windowed ? resizeItem : undefined} />
		: <SectionNoteRow key={item.id} item={item} index={documentIndex} {...windowProps} />;
};

/**
 * The КП line table: sticky header, the (optionally windowed) body of `GridRow`s, and the
 * «добавить и продолжить» add-row. Above VIRTUALIZE_THRESHOLD rows the body renders only the
 * visible window plus two spacer rows (paddingTop/paddingBottom), which keeps the real `<table>`
 * flow — so sticky-left columns and the sticky `<thead>` survive the scroll unchanged. At or below
 * the threshold every row renders normally (byte-identical to the pre-virtualization grid).
 */
export const GridTable: React.FC = () => {
	const { t } = useTranslation();
	const {
		scrollContainerRef, gridKeyboardOnKeyDown, handleGridPaste, selection, showCostColumns,
		visibleItems, documentIndexById, isFiltered, virtualizer, shouldVirtualize, mainColCount,
		showAddRow, newItemName, setNewItemName, newItemQty, setNewItemQty, newItemPrice,
		setNewItemPrice, handleAddItem, setShowAddRow, addNameRef, addRowRef, createItemPending,
	} = useQuoteBuilderGrid();

	// U4: the body renders the (possibly filtered) VISIBLE rows, but each row keeps its real place in
	// the document for its number and aria-labels — a filtered line is still «позиция 12».
	const rowIndexOf = (item: QuoteItem, fallback: number) => documentIndexById.get(item.id) ?? fallback;

	const virtualItems = shouldVirtualize ? virtualizer.getVirtualItems() : [];
	const paddingTop = virtualItems.length > 0 ? virtualItems[0].start : 0;
	const paddingBottom = virtualItems.length > 0
		? virtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end
		: 0;

	return (
		<div className="flex-1 overflow-auto rounded-md border" ref={scrollContainerRef} onKeyDown={gridKeyboardOnKeyDown} onPaste={handleGridPaste}>
			<TooltipProvider>
				<Table className="w-full text-left text-sm">
					<TableHeader className="sticky top-0 z-20 border-b bg-muted">
						<TableRow>
							<TableHead className="w-8 px-1 py-2 text-center sticky left-0 z-30 bg-muted">
								{/* DT7: `onCheckedChange` (not `onClick`) so keyboard toggling reports the same way. */}
								<Checkbox
									checked={selection.allSelected ? true : selection.someSelected ? 'indeterminate' : false}
									onCheckedChange={() => selection.toggleAll()}
									aria-label={t('quote.bulk.selectAll')}
								/>
							</TableHead>
							{/* DT9: `w-10` (was `w-8`) — the chevron + row-error marker stack was cramped. The
							    name column's sticky offset follows it (left-8 + w-10 → left-18). */}
							<TableHead className="w-10 px-1 py-2 sticky left-8 z-30 bg-muted" />
							{/* B2: `w-full` on the name header makes it the elastic absorber — the table gives it
							    every pixel the fixed numeric columns don't claim, instead of truncating early. */}
							{/* B1: the name column is `w-full` (elastic absorber) but NOT horizontally sticky.
							    A `position:sticky` cell with `width:100%` overflows its own column box by ~44px
							    and, being z-30 + opaque, painted over the left of the «Кол-во» header (→ «л-во»).
							    The frozen identity anchor stays the checkbox + chevron; the name scrolls. */}
							<TableHead className="w-full px-2 py-2 text-xs font-semibold text-muted-foreground min-w-[200px] bg-muted">
								{t('catalog.table.name')}
							</TableHead>
							<TableHead className="px-2 py-2 text-center text-xs font-semibold text-muted-foreground w-20">
								<Tooltip>
									<TooltipTrigger asChild><span className="cursor-help">{t('quote.quantity')}</span></TooltipTrigger>
									<TooltipContent>{t('quote.quantityHelp')}</TooltipContent>
								</Tooltip>
							</TableHead>
							{showCostColumns && (
								<TableHead className="px-2 py-2 text-xs font-semibold text-muted-foreground w-52 bg-muted/30">
									<Tooltip>
										<TooltipTrigger asChild><span className="cursor-help">{t('quote.basePrice')}</span></TooltipTrigger>
										<TooltipContent>{t('quote.basePriceHelp')}</TooltipContent>
									</Tooltip>
								</TableHead>
							)}
							{showCostColumns && (
								// DT1: was `w-16` for a read-only chip; the cell is now an input plus a
								// conditional revert button, so it needs the extra 32px. The name column is
								// the `w-full` elastic absorber, so this comes out of slack, not out of it.
								<TableHead className="px-2 py-2 text-center text-xs font-semibold text-muted-foreground w-24">
									<Tooltip>
										<TooltipTrigger asChild><span className="cursor-help">{t('quote.marginOverride.header')}</span></TooltipTrigger>
										<TooltipContent>{t('quote.marginOverride.headerHelp')}</TooltipContent>
									</Tooltip>
								</TableHead>
							)}
							<TableHead className="px-2 py-2 text-right text-xs font-semibold text-muted-foreground w-32 pr-4">
								{t('quote.lineTotal')}
							</TableHead>
							{/* U1: the actions column now carries TWO icon columns (опция/удалить + ↑/↓). */}
							<TableHead className="px-2 py-2 w-14" />
						</TableRow>
					</TableHeader>
					<TableBody className="divide-y">
						{shouldVirtualize ? (
							<>
								{paddingTop > 0 && (
									// `border-t-0!` (important) drops the faint line `divide-y` would draw on this
									// windowing spacer — its selector out-specifies a plain class, so !important wins.
									<tr aria-hidden="true" className="border-t-0!">
										<td colSpan={mainColCount} style={{ height: paddingTop }} />
									</tr>
								)}
								{virtualItems.map((virtualRow) => {
									const item = visibleItems[virtualRow.index];
									return renderGridRow(
										item,
										rowIndexOf(item, virtualRow.index),
										virtualRow.index,
										virtualizer.measureElement,
										virtualizer.resizeItem,
									);
								})}
								{paddingBottom > 0 && (
									<tr aria-hidden="true" className="border-t-0!">
										<td colSpan={mainColCount} style={{ height: paddingBottom }} />
									</tr>
								)}
							</>
						) : (
							visibleItems.map((item, idx) => renderGridRow(item, rowIndexOf(item, idx), undefined, () => {}, () => {}))
						)}
						{/* U4: an active filter that matches nothing must SAY so — an empty table would read
						    as «в КП нет позиций», which is a lie about a document that still has lines. */}
						{isFiltered && visibleItems.length === 0 && (
							<TableRow>
								<TableCell colSpan={mainColCount} className="px-4 py-6 text-center text-sm text-muted-foreground">
									{t('quote.filter.noMatches')}
								</TableCell>
							</TableRow>
						)}
						{showAddRow && (
							<TableRow ref={addRowRef} className="bg-primary/5">
								<TableCell className="px-2 py-1.5 text-center text-xs text-muted-foreground">+</TableCell>
								<TableCell className="p-1" colSpan={mainColCount - 1}>
									{/* Быстрый ввод (spec §5 п.7): наименование + кол-во + базовая цена. Enter =
									    «добавить и продолжить» (строка остаётся, фокус возвращается в наименование);
									    Escape закрывает строку добавления. */}
									<div
										className="flex flex-wrap items-center gap-2"
										onKeyDown={(event) => {
											if (event.key === 'Enter') {
												event.preventDefault();
												handleAddItem();
											} else if (event.key === 'Escape') {
												event.preventDefault();
												setShowAddRow(false);
											}
										}}
									>
										<Input
											ref={addNameRef}
											type="text"
											value={newItemName}
											onChange={e => setNewItemName(e.target.value)}
											placeholder={t('quote.addItemPlaceholder')}
											aria-label={t('catalog.table.name')}
											className="h-7 min-w-[200px] flex-1 text-sm"
											autoFocus
										/>
										<Input
											type="text"
											inputMode="numeric"
											value={newItemQty}
											onChange={e => setNewItemQty(e.target.value)}
											aria-label={t('quote.quantity')}
											className="h-7 w-20 text-sm text-center"
										/>
										<Input
											type="text"
											inputMode="decimal"
											value={newItemPrice}
											onChange={e => setNewItemPrice(e.target.value)}
											aria-label={t('quote.basePrice')}
											className="h-7 w-32 text-sm font-mono text-right"
										/>
										<Button size="sm" onClick={handleAddItem} disabled={!newItemName.trim() || createItemPending}>
											{t('common.add')}
										</Button>
									</div>
								</TableCell>
							</TableRow>
						)}
					</TableBody>
				</Table>
			</TooltipProvider>
		</div>
	);
};
