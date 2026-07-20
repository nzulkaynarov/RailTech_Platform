import React from 'react';
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
import { QUOTE_ITEM_MAX_QUANTITY, QUOTE_ITEM_MAX_UNIT_PRICE, marginToneClass } from './gridConstants';
import { useQuoteBuilderGrid } from './QuoteBuilderGridContext';

interface GridRowProps {
	item: QuoteItem;
	/** 0-based row index in the visible (draftItems) order — drives aria-labels + the row number. */
	index: number;
	/** Virtualizer index for `data-index` (windowed rendering only). */
	virtualIndex?: number;
	/** Virtualizer's dynamic-height measure callback (windowed rendering only). */
	measureElement?: (node: Element | null) => void;
}

/**
 * One КП line: the main row (checkbox · expander · name · qty · [cost/margin] · sum · delete) plus
 * its collapsible detail sub-row (HS-code, customs, lead time, discount, line economics). Extracted
 * verbatim from the former monolithic grid — every data-cell attribute, sticky offset and class is
 * unchanged, so keyboard navigation, sticky columns and the row-error marker behave exactly as before.
 */
export const GridRow: React.FC<GridRowProps> = ({ item, index, virtualIndex, measureElement }) => {
	const { t } = useTranslation();
	const {
		econ, canViewCost, showCostColumns, presentationCurrency, currencies,
		pricingMirror, selection, handleFieldChange, cellError, cellErrors, hiddenErrorFields,
		fieldLabel, expandedRowId, toggleRow, setExpandedRowId, fxRateFor, lineCostInPresentation,
		handleDeleteItem, setReassignItemId, rowRefs, mainColCount,
	} = useQuoteBuilderGrid();

	// Per-line economics (advisory chip) — sourced from the live mirror so a dirty row's margin/loss
	// triage tracks the in-progress edit. Returns null when cost is hidden/unknown.
	const lineSignal = (row: QuoteItem) => {
		const line = pricingMirror.lineFor(row);
		if (line.marginPct == null || line.profit == null) return null;
		return { marginPct: line.marginPct, profit: line.profit, belowCost: line.belowCost, belowFloor: line.belowFloor };
	};

	// F6/WP-7: the per-line margin is DERIVED and READ-ONLY — the markup is a single value for the
	// whole КП. Render it muted with a «Настройки КП» hint icon so it can't be mistaken for an input.
	const marginCell = (row: QuoteItem) => {
		if (!canViewCost || !econ) return <span className="text-xs text-muted-foreground">—</span>;
		const sig = lineSignal(row);
		if (!sig) return <span className="text-xs text-muted-foreground">—</span>;
		return (
			<Tooltip>
				<TooltipTrigger asChild>
					<span className="inline-flex cursor-help select-none items-center justify-center gap-1 text-xs tabular-nums text-muted-foreground">
						{sig.marginPct.toFixed(0)}%
						<Settings className="size-3 opacity-60" aria-hidden="true" />
					</span>
				</TooltipTrigger>
				<TooltipContent>
					<div className="flex flex-col gap-0.5">
						<span>{t('quote.economics.landedCost')}: {formatMoney(pricingMirror.lineFor(row).landedCost ?? row.landed_cost, presentationCurrency)}</span>
						<span>{t('quote.lineProfit')}: {formatMoney(sig.profit, presentationCurrency)}</span>
						<span className="mt-0.5 font-medium text-foreground">{t('quote.marginQuoteLevelHint')}</span>
					</div>
				</TooltipContent>
			</Tooltip>
		);
	};

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

	// Combined row ref: keeps the parent's per-id map (bulk-reject scroll-into-view) AND feeds the
	// virtualizer's dynamic-height measurement when the table is windowed.
	const setRowRef = (element: HTMLTableRowElement | null) => {
		if (element) rowRefs.current.set(item.id, element);
		else rowRefs.current.delete(item.id);
		measureElement?.(element);
	};

	// Measure the expanded detail sub-row too (WP-review): the virtualizer keys a ResizeObserver by
	// `data-index`, and in a real `<table>` a row-group is two sibling `<tr>`s that can't share one
	// wrapper — so the detail row carries the SAME data-index and re-registers with `measureElement`.
	// It's a fresh closure per render (unlike the stable `measureElement`) so it re-runs AFTER the main
	// row on every re-render and stays the observed node while expanded — otherwise the taller detail
	// height would be dropped from getTotalSize() and a >50-line КП would scroll-drift on expand.
	const setDetailRef = (element: HTMLTableRowElement | null) => {
		measureElement?.(element);
	};

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
					<Checkbox
						checked={isRowSelected}
						onClick={(event) => selection.toggle(item.id, (event as React.MouseEvent).shiftKey)}
						aria-label={t('quote.bulk.selectRow', { index: index + 1 })}
					/>
				</TableCell>
				<TableCell className={cn('w-8 px-1 py-1.5 text-center sticky left-8 z-10', stickyBg)}>
					{/* Stack vertically: the chevron (20px) + the bulk-error marker (16px) would overflow the
					    32px `w-8` cell side-by-side; column layout keeps both centred and inside the cell. */}
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
				<TableCell className={cn('px-2 py-1.5 sticky left-16 z-10', stickyBg)}>
					<div className="flex items-center gap-2">
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
					<TableCell className="px-2 py-1.5 text-center">{marginCell(item)}</TableCell>
				)}
				<TableCell className="px-2 py-1.5 text-right pr-4">
					{(() => {
						// Live «Сумма» from the mirror: for a dirty row this is the preview
						// (marked «черновик» in italics); a needsServerRecalc row shows the
						// server total with a «пересчёт после сохранения» hint (honest, not faked).
						const line = pricingMirror.lineFor(item);
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
						<Button variant="ghost" size="icon-xs" onClick={() => handleDeleteItem(item.id)} className="text-muted-foreground hover:text-destructive" title={t('common.delete')}>
							<Trash2 className="size-3" />
						</Button>
					</div>
				</TableCell>
			</TableRow>
			{isExpanded && (
				<TableRow ref={setDetailRef} data-index={virtualIndex} className="bg-muted/30">
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
										{t('quote.economics.landedCost')}: <span className="font-semibold tabular-nums text-foreground">{formatMoney(pricingMirror.lineFor(item).landedCost ?? item.landed_cost, presentationCurrency)}</span>
									</span>
									{(() => {
										const sig = lineSignal(item);
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
