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
	index: number,
	windowed: boolean,
	measureElement: (node: Element | null) => void,
	resizeItem: (index: number, size: number) => void,
) => {
	const windowProps = windowed ? { virtualIndex: index, measureElement } : {};
	return (item.display_type ?? 'ITEM') === 'ITEM'
		? <GridRow key={item.id} item={item} index={index} {...windowProps} resizeItem={windowed ? resizeItem : undefined} />
		: <SectionNoteRow key={item.id} item={item} index={index} {...windowProps} />;
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
		draftItems, virtualizer, shouldVirtualize, mainColCount,
		showAddRow, newItemName, setNewItemName, newItemQty, setNewItemQty, newItemPrice,
		setNewItemPrice, handleAddItem, setShowAddRow, addNameRef, addRowRef, createItemPending,
	} = useQuoteBuilderGrid();

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
							<TableHead className="w-full px-2 py-2 text-xs font-semibold text-muted-foreground min-w-[200px] sticky left-18 z-30 bg-muted">
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
								<TableHead className="px-2 py-2 text-center text-xs font-semibold text-muted-foreground w-16">
									{t('quote.marginApplied')}
								</TableHead>
							)}
							<TableHead className="px-2 py-2 text-right text-xs font-semibold text-muted-foreground w-32 pr-4">
								{t('quote.lineTotal')}
							</TableHead>
							<TableHead className="px-2 py-2 w-8" />
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
									const item = draftItems[virtualRow.index];
									return renderGridRow(item, virtualRow.index, true, virtualizer.measureElement, virtualizer.resizeItem);
								})}
								{paddingBottom > 0 && (
									<tr aria-hidden="true" className="border-t-0!">
										<td colSpan={mainColCount} style={{ height: paddingBottom }} />
									</tr>
								)}
							</>
						) : (
							draftItems.map((item, idx) => renderGridRow(item, idx, false, () => {}, () => {}))
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
