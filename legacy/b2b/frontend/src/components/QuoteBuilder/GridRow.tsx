import React, { useCallback, useLayoutEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, ChevronDown, AlertCircle, Settings, Trash2 } from 'lucide-react';
import type { QuoteItem } from '@/api/crmApi';
import { cn } from '@/lib/utils';
import { formatMoney } from '@/utils/decimal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { TableRow, TableCell } from '@/components/ui/table';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { NumericCell } from './NumericCell';
import { ProductNameCell } from './ProductNameCell';
import { RowSelectCheckbox } from './RowSelectCheckbox';
import { QUOTE_ITEM_MAX_QUANTITY, QUOTE_ITEM_MAX_UNIT_PRICE, marginToneClass } from './gridConstants';
import { useQuoteBuilderGrid } from './QuoteBuilderGridContext';
import { lineSignalOf, type LineSignal } from './lineSignal';

interface GridRowProps {
	item: QuoteItem;
	/** 0-based row index in the visible (draftItems) order — drives aria-labels + the row number. */
	index: number;
	/** Virtualizer index for `data-index` (windowed rendering only). */
	virtualIndex?: number;
	/** Virtualizer's dynamic-height measure callback (windowed rendering only). */
	measureElement?: (node: Element | null) => void;
	/** Virtualizer's explicit size setter — reports main-row + detail-row height as ONE index (B3). */
	resizeItem?: (index: number, size: number) => void;
}

interface MarginCellProps {
	signal: LineSignal | null;
	landedCost: string | null;
	presentationCurrency: string;
}

/**
 * F6/WP-7: the per-line margin is DERIVED and READ-ONLY — the markup is a single value for the
 * whole КП. Rendered muted with a «Настройки КП» hint icon so it can't be mistaken for an input.
 * Hoisted to a memoized module-level component (DT4) so a facade re-render that leaves the row's
 * numbers untouched no longer re-renders every visible margin chip.
 */
const MarginCell: React.FC<MarginCellProps> = React.memo(({ signal, landedCost, presentationCurrency }) => {
	const { t } = useTranslation();
	if (!signal) return <span className="text-xs text-muted-foreground">—</span>;
	return (
		<Tooltip>
			<TooltipTrigger asChild>
				<span className="inline-flex cursor-help select-none items-center justify-center gap-1 text-xs tabular-nums text-muted-foreground">
					{signal.marginPct.toFixed(0)}%
					<Settings className="size-3 opacity-60" aria-hidden="true" />
				</span>
			</TooltipTrigger>
			<TooltipContent>
				<div className="flex flex-col gap-0.5">
					<span>{t('quote.economics.landedCost')}: {formatMoney(landedCost, presentationCurrency)}</span>
					<span>{t('quote.lineProfit')}: {formatMoney(signal.profit, presentationCurrency)}</span>
					<span className="mt-0.5 font-medium text-foreground">{t('quote.marginQuoteLevelHint')}</span>
				</div>
			</TooltipContent>
		</Tooltip>
	);
});
MarginCell.displayName = 'MarginCell';

/**
 * One КП line: the main row (checkbox · expander · name · qty · [cost/margin] · sum · delete) plus
 * its collapsible detail sub-row (HS-code, customs, lead time, discount, line economics). Every
 * data-cell attribute and sticky offset is preserved, so keyboard navigation, sticky columns and the
 * row-error marker behave exactly as before.
 *
 * Virtualization contract (B3): EXACTLY ONE measured node per virtual index. The main row carries
 * `data-index` and the (stable) `measureElement` ref; the detail sub-row carries NEITHER — instead a
 * layout effect reports `main + detail` height through `resizeItem`, so `getTotalSize()` stays honest
 * while a row is expanded and the window never drifts.
 */
const GridRowComponent: React.FC<GridRowProps> = ({ item, index, virtualIndex, measureElement, resizeItem }) => {
	const { t } = useTranslation();
	const {
		econ, canViewCost, showCostColumns, presentationCurrency, currencies,
		pricingMirror, selection, handleFieldChange, cellError, cellErrors, hiddenErrorFields,
		fieldLabel, expandedRowId, toggleRow, setExpandedRowId, fxRateFor, lineCostInPresentation,
		handleDeleteItem, setReassignItemId, rowRefs, mainColCount,
	} = useQuoteBuilderGrid();

	const mirrorLine = pricingMirror.lineFor(item);
	const signal = canViewCost && econ ? lineSignalOf(mirrorLine) : null;

	const isExpanded = expandedRowId === item.id;
	const isRowSelected = selection.isSelected(item.id);
	// S1: опциональная позиция — показывается с ценой, но её сумма НЕ входит в итоги/маржу КП.
	// Визуально: бейдж «опц.» у наименования + приглушённая строка (управление остаётся кликабельным).
	const isOptional = !!item.is_optional;
	const rowHiddenErrors = hiddenErrorFields(cellErrors, item.id, showCostColumns);
	// Sticky-cell background: selection tint overrides the plain surface; hover/focus win.
	const stickyBg = cn(
		isRowSelected ? 'bg-primary/10' : 'bg-background',
		'group-hover:bg-muted/50 group-focus-within:bg-muted/40',
	);

	const mainRowRef = useRef<HTMLTableRowElement | null>(null);
	const detailRowRef = useRef<HTMLTableRowElement | null>(null);

	// Combined row ref: keeps the parent's per-id map (bulk-reject scroll-into-view) AND feeds the
	// virtualizer's dynamic-height measurement when the table is windowed.
	//
	// B3 (1): this MUST be referentially stable. A fresh arrow per render makes React detach/re-attach
	// the ref on every re-render of the facade, which unobserves + re-observes the node in the
	// virtualizer's ResizeObserver — the churn re-enters the measurement path mid-scroll and snaps the
	// window back to the top. `item.id`, `measureElement` (virtualizer instance method) and `rowRefs`
	// (a ref object) are all stable, so this callback is created once per row.
	const setRowRef = useCallback((element: HTMLTableRowElement | null) => {
		mainRowRef.current = element;
		if (element) rowRefs.current.set(item.id, element);
		else rowRefs.current.delete(item.id);
		measureElement?.(element);
	}, [item.id, measureElement, rowRefs]);

	// B3 (2): the detail sub-row is deliberately NOT measured and carries NO `data-index` — a real
	// `<table>` row-group is two sibling `<tr>`s that cannot share a wrapper, and letting both claim
	// the same index meant only the detail landed in the height cache (the main row's height was
	// dropped from getTotalSize(), so a long КП drifted as soon as a row was expanded). Instead the
	// effect below reports the COMBINED height for the one index that owns this line.
	useLayoutEffect(() => {
		if (virtualIndex == null || !resizeItem) return;
		const main = mainRowRef.current;
		if (!main) return;
		const detailHeight = detailRowRef.current?.getBoundingClientRect().height ?? 0;
		resizeItem(virtualIndex, main.getBoundingClientRect().height + detailHeight);
		// `isExpanded` is what changes the pair's height; re-report on mount and on every toggle.
	}, [virtualIndex, resizeItem, isExpanded]);

	return (
		<React.Fragment>
			<TableRow
				ref={setRowRef}
				data-row-id={item.id}
				data-index={virtualIndex}
				data-display-type={item.display_type ?? 'ITEM'}
				className={cn(
					'hover:bg-muted/50 focus-within:bg-muted/40 transition-colors group',
					isRowSelected && 'bg-primary/5',
					isOptional && 'opacity-60',
				)}
			>
				<TableCell className={cn('w-8 px-1 py-1.5 text-center sticky left-0 z-10', stickyBg)}>
					<RowSelectCheckbox
						checked={isRowSelected}
						onToggle={(shiftKey) => selection.toggle(item.id, shiftKey)}
						ariaLabel={t('quote.bulk.selectRow', { index: index + 1 })}
					/>
				</TableCell>
				<TableCell className={cn('w-10 px-1 py-1.5 text-center sticky left-8 z-10', stickyBg)}>
					{/* Stack vertically: the chevron (20px) + the bulk-error marker (16px) would overflow the
					    cell side-by-side; column layout keeps both centred and inside the cell. DT9: the
					    column is `w-10` (40px) so the stacked pair is no longer cramped on narrow screens. */}
					<div className="flex flex-col items-center justify-center gap-0.5">
						<button
							type="button"
							onClick={(e) => { e.stopPropagation(); toggleRow(item.id); }}
							aria-expanded={isExpanded}
							aria-controls={`kp-line-detail-${item.id}`}
							aria-label={t('quote.lineDetails')}
							className="flex size-5 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
						>
							{isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
						</button>
						{/* Row error marker: an error on a field hidden in the collapsed detail (or a
						    cost column dropped on a narrow screen). Click → expand the detail. */}
						{rowHiddenErrors.length > 0 && (
							<Tooltip>
								<TooltipTrigger asChild>
									<button
										type="button"
										onClick={(e) => { e.stopPropagation(); setExpandedRowId(item.id); }}
										aria-label={t('quote.rowError.marker')}
										className="flex size-4 items-center justify-center rounded text-destructive hover:bg-destructive/10"
									>
										<AlertCircle className="size-3.5" />
									</button>
								</TooltipTrigger>
								<TooltipContent>
									<div className="flex flex-col gap-0.5">
										<span className="font-medium">{t('quote.rowError.marker')}</span>
										<span className="text-muted-foreground">
											{t('quote.rowError.fields')} {rowHiddenErrors.map(fieldLabel).join(', ')}
										</span>
									</div>
								</TooltipContent>
							</Tooltip>
						)}
					</div>
				</TableCell>
				{/* B2: `w-full` makes the name the ELASTIC absorber column — every other column is fixed
				    (`w-20`/`w-52`/`w-16`/`w-32`/`w-8`), so the table hands all remaining width here instead
				    of truncating early and leaving dead space on the right. `min-w-0` on the flex wrapper
				    lets the inner input actually shrink below its content width (default `min-width:auto`
				    would otherwise block the chain). */}
				<TableCell className={cn('w-full px-2 py-1.5 sticky left-18 z-10', stickyBg)}>
					<div className="flex min-w-0 w-full items-center gap-2">
						{isOptional && (
							<Badge variant="outline" className="shrink-0 text-xs font-normal text-muted-foreground">
								{t('quote.optional.badge')}
							</Badge>
						)}
						<ProductNameCell
							item={item}
							index={index + 1}
							onBrowseCandidates={setReassignItemId}
						/>
					</div>
				</TableCell>
				<TableCell className="p-0">
					<NumericCell
						min={1}
						max={QUOTE_ITEM_MAX_QUANTITY}
						maxToastKey="quote.validation.qtyTooLarge"
						maxFractionDigits={0}
						ariaLabel={t('quote.quantity')}
						className="h-8 border-none shadow-none rounded-none text-xs font-semibold text-center focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
						dataCellRow={item.id}
						dataCellCol="quantity"
						value={item.quantity}
						invalid={!!cellError(item.id, 'quantity')}
						errorMessage={cellError(item.id, 'quantity')}
						onCommit={(value) => handleFieldChange(item.id, 'quantity', value)}
					/>
				</TableCell>
				{showCostColumns && (
					<TableCell className="p-0 bg-muted/20">
						<div className="flex items-center">
							<Tooltip>
								<TooltipTrigger asChild>
									<span className="flex-1">
										<NumericCell
											min={0}
											max={QUOTE_ITEM_MAX_UNIT_PRICE}
											maxToastKey="quote.validation.priceTooLarge"
											ariaLabel={t('quote.basePrice')}
											className="h-8 w-full border-none shadow-none rounded-none text-xs font-mono text-right pr-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
											dataCellRow={item.id}
											dataCellCol="frozen_base_price"
											value={item.frozen_base_price}
											invalid={!!cellError(item.id, 'frozen_base_price')}
											errorMessage={cellError(item.id, 'frozen_base_price')}
											onCommit={(value) => handleFieldChange(item.id, 'frozen_base_price', value)}
										/>
									</span>
								</TooltipTrigger>
								<TooltipContent>
									<div className="flex flex-col gap-0.5">
										<span>{t('quote.costInPresentation', { value: formatMoney(lineCostInPresentation(item), presentationCurrency) })}</span>
										{(item.frozen_currency || 'UZS').toUpperCase() !== 'UZS' && (
											<span className="text-muted-foreground">
												{t('quote.fxRateAt', { rate: fxRateFor(item.frozen_currency), from: (item.frozen_currency || 'UZS').toUpperCase(), to: presentationCurrency })}
											</span>
										)}
									</div>
								</TooltipContent>
							</Tooltip>
							<Select value={item.frozen_currency || 'UZS'} onValueChange={(code) => handleFieldChange(item.id, 'frozen_currency', code)}>
								<SelectTrigger
									aria-label={t('quote.lineCurrency')}
									aria-invalid={!!cellError(item.id, 'frozen_currency') || undefined}
									title={cellError(item.id, 'frozen_currency')}
									className={cn('h-8 w-20 shrink-0 border-none shadow-none rounded-none text-xs focus:ring-1', cellError(item.id, 'frozen_currency') && 'border-destructive ring-1 ring-destructive')}
								>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									{currencies.map((ccy) => (<SelectItem key={ccy.id} value={ccy.code}>{ccy.code}</SelectItem>))}
								</SelectContent>
							</Select>
						</div>
					</TableCell>
				)}
				{showCostColumns && (
					<TableCell className="px-2 py-1.5 text-center">
						<MarginCell
							signal={signal}
							landedCost={mirrorLine.landedCost ?? item.landed_cost ?? null}
							presentationCurrency={presentationCurrency}
						/>
					</TableCell>
				)}
				<TableCell className="px-2 py-1.5 text-right pr-4">
					{(() => {
						// Live «Сумма» from the mirror: for a dirty row this is the preview
						// (marked «черновик» in italics); a needsServerRecalc row shows the
						// server total with a «пересчёт после сохранения» hint (honest, not faked).
						const line = mirrorLine;
						const money = formatMoney(line.lineTotal, presentationCurrency);
						if (line.needsServerRecalc) {
							return (
								<Tooltip>
									<TooltipTrigger asChild>
										<span className="cursor-help text-sm font-bold italic tabular-nums text-muted-foreground">{money} ~</span>
									</TooltipTrigger>
									<TooltipContent>{t('quote.draftRecalcOnSave')}</TooltipContent>
								</Tooltip>
							);
						}
						if (line.usedMarketFx) {
							// Priced off the PRELIMINARY public market rate — a live preview, but the
							// server freezes its own rate on save. Flag it so we never pass the market
							// rate off as the frozen one.
							return (
								<Tooltip>
									<TooltipTrigger asChild>
										<span className="cursor-help text-sm font-bold italic tabular-nums text-primary">≈ {money} ~</span>
									</TooltipTrigger>
									<TooltipContent>{t('quote.marketFxPreview')}</TooltipContent>
								</Tooltip>
							);
						}
						return (
							<span
								className={cn('text-sm font-bold tabular-nums', line.isDraft && 'italic text-primary')}
								title={line.isDraft ? t('quote.draftPreview') : undefined}
							>
								{line.isDraft ? '≈ ' : ''}{money}
							</span>
						);
					})()}
				</TableCell>
				<TableCell className="px-1 py-0.5">
					{/* Stack the «опция» toggle above delete — two icon-sized controls won't fit side by
					    side in the narrow w-8 actions cell (mirrors the chevron/error-marker column). */}
					<div className="flex flex-col items-center gap-1">
						<Tooltip>
							<TooltipTrigger asChild>
								<span className="flex items-center justify-center">
									<Checkbox
										checked={isOptional}
										onCheckedChange={(checked) => handleFieldChange(item.id, 'is_optional', checked === true)}
										aria-label={t('quote.optional.toggle')}
										className="size-3.5"
									/>
								</span>
							</TooltipTrigger>
							<TooltipContent>{t('quote.optional.toggle')}</TooltipContent>
						</Tooltip>
						{/* DT7: an icon-only control needs an accessible NAME, not just a hover `title`.
						    The row number disambiguates it in the a11y tree across ~60 identical rows. */}
						<Button
							variant="ghost"
							size="icon-xs"
							onClick={() => handleDeleteItem(item.id)}
							className="text-muted-foreground hover:text-destructive"
							title={t('common.delete')}
							aria-label={t('quote.row.deleteAria', { index: index + 1 })}
						>
							<Trash2 className="size-3" />
						</Button>
					</div>
				</TableCell>
			</TableRow>
			{isExpanded && (
				// NO `data-index` and NO `measureElement` here — see the B3 note above: exactly one
				// measured node per virtual index. The layout effect reports main+detail height instead.
				<TableRow ref={detailRowRef} className="bg-muted/30">
					<TableCell colSpan={mainColCount} className="p-0">
						<div id={`kp-line-detail-${item.id}`} className="sticky left-0 flex max-w-full flex-col gap-3 px-4 py-3">
							<span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('quote.lineDetails')}</span>
							<div className="flex flex-wrap gap-4">
								<label className="flex flex-col gap-1">
									<span className="text-xs text-muted-foreground">{t('quote.hsCode')}</span>
									<Input
										type="text"
										placeholder={t('quote.hsCode')}
										aria-invalid={!!cellError(item.id, 'hs_code') || undefined}
										title={cellError(item.id, 'hs_code')}
										className={cn('h-8 w-40 text-xs font-mono', cellError(item.id, 'hs_code') && 'border-destructive ring-1 ring-destructive')}
										value={item.hs_code || ''}
										onChange={(e) => handleFieldChange(item.id, 'hs_code', e.target.value)}
									/>
								</label>
								{canViewCost && (
									<label className="flex flex-col gap-1">
										<span className="text-xs text-muted-foreground">{t('quote.customsDuty')}</span>
										<NumericCell
											min={0}
											max={QUOTE_ITEM_MAX_UNIT_PRICE}
											maxToastKey="quote.validation.priceTooLarge"
											ariaLabel={t('quote.customsDuty')}
											className="h-8 w-32 text-xs font-mono text-right"
											value={item.customs_duty}
											invalid={!!cellError(item.id, 'customs_duty')}
											errorMessage={cellError(item.id, 'customs_duty')}
											onCommit={(value) => handleFieldChange(item.id, 'customs_duty', value)}
										/>
									</label>
								)}
								<label className="flex flex-col gap-1">
									<span className="text-xs text-muted-foreground">{t('quote.leadTime')}</span>
									<NumericCell
										min={0}
										maxFractionDigits={0}
										ariaLabel={t('quote.leadTime')}
										className="h-8 w-24 text-xs text-center"
										value={item.lead_time_days ?? 0}
										invalid={!!cellError(item.id, 'lead_time_days')}
										errorMessage={cellError(item.id, 'lead_time_days')}
										onCommit={(value) => handleFieldChange(item.id, 'lead_time_days', value)}
									/>
								</label>
								{canViewCost && (
									<label className="flex flex-col gap-1">
										<span className="text-xs text-muted-foreground">{t('quote.discountPercent')}</span>
										<NumericCell
											min={0}
											max={100}
											ariaLabel={t('quote.discountPercent')}
											className="h-8 w-24 text-xs text-center"
											value={item.discount_percent ?? 0}
											invalid={!!cellError(item.id, 'discount_percent')}
											errorMessage={cellError(item.id, 'discount_percent')}
											onCommit={(value) => handleFieldChange(item.id, 'discount_percent', value)}
										/>
									</label>
								)}
							</div>
							{canViewCost && (
								<div className="flex flex-wrap gap-6 border-t pt-2 text-xs">
									<span className="text-muted-foreground">
										{t('quote.economics.landedCost')}: <span className="font-semibold tabular-nums text-foreground">{formatMoney(mirrorLine.landedCost ?? item.landed_cost, presentationCurrency)}</span>
									</span>
									{(() => {
										const sig = signal;
										if (!sig) return null;
										return (
											<>
												<span className="text-muted-foreground">
													{t('quote.lineProfit')}: <span className="font-semibold tabular-nums text-foreground">{formatMoney(sig.profit, presentationCurrency)}</span>
												</span>
												<span className="text-muted-foreground">
													{t('quote.economics.grossMargin')}: <span className={cn('font-semibold tabular-nums', econ ? marginToneClass(sig.belowCost || sig.belowFloor, sig.marginPct, Number(econ.target_margin_percent)) : '')}>{sig.marginPct.toFixed(1)}%</span>
												</span>
											</>
										);
									})()}
								</div>
							)}
						</div>
					</TableCell>
				</TableRow>
			)}
		</React.Fragment>
	);
};
GridRowComponent.displayName = 'GridRow';

/**
 * DT4: memoized so a virtualizer-driven re-render of `GridTable` (which fires on every scroll frame)
 * no longer re-renders all ~20 visible rows. All five props are stable across such a render —
 * `measureElement`/`resizeItem` are virtualizer instance methods and `item` keeps its identity while
 * the row is untouched. NOTE: `GridRow` also consumes the grid CONTEXT, and a context-value change
 * still re-renders every row regardless of this memo — the win here is the scroll path, not a
 * facade state change.
 */
export const GridRow = React.memo(GridRowComponent);
