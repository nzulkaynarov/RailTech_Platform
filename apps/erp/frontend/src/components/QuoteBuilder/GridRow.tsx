import React, { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, ChevronDown, ChevronUp, AlertCircle, Landmark, RotateCcw, Trash2 } from 'lucide-react';
import type { QuoteItem } from '@/api/crmApi';
import { cn } from '@/lib/utils';
import { CustomsDutiesSheet } from '@/components/Shared/CustomsDutiesSheet';
import { formatMoney } from '@/utils/decimal';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { TableRow, TableCell } from '@/components/ui/table';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { NumericCell } from './NumericCell';
import { ProductNameCell } from './ProductNameCell';
import { RowSelectCheckbox } from './RowSelectCheckbox';
import {
	QUOTE_ITEM_MAX_QUANTITY, QUOTE_ITEM_MAX_UNIT_PRICE, QUOTE_ITEM_MAX_MARGIN_PERCENT, marginToneClass,
} from './gridConstants';
import { useQuoteBuilderGrid } from './QuoteBuilderGridContext';
import { lineSignalOf, type LineSignal } from './lineSignal';
import type { LineMirror } from './usePricingMirror';
import { HSCodeField } from '@/components/Shared/HSCodeField';

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
	/** 1-based document position — disambiguates the cell's accessible name across ~60 rows. */
	index: number;
	/** Row id — feeds `data-cell-row` so keyboard nav (↑/↓/Tab across the window) resolves this cell
	 *  by the SAME id every other column uses; the position `index` is display-only. */
	rowId: number;
	/** Live markup actually applied to this line + whether it is an explicit override (DT1). */
	line: LineMirror;
	/** The КП-level markup this line falls back to — rendered as the inherit placeholder. */
	quoteMarginPercent: string | number | null | undefined;
	signal: LineSignal | null;
	landedCost: string | null;
	presentationCurrency: string;
	/** Только чтение: ячейка заблокирована, кнопки отката наценки нет. */
	readOnly?: boolean;
	invalid: boolean;
	errorMessage?: string;
	/** Write an explicit per-line override (a numeric string). */
	onCommit: (value: string) => void;
	/** Drop the override → the line inherits the КП margin again. MUST write null, never «0». */
	onRevert: () => void;
}

/**
 * DT1 — the per-line margin OVERRIDE cell (Salesforce CPQ / Odoo semantics).
 *
 * It used to be a read-only chip: the markup was a single КП-wide value, so the cell showed the
 * derived gross margin with a «Настройки КП» hint. The backend now stores a nullable per-line
 * `margin_percent` where NULL means «наследовать маржу КП» and any non-null value overrides it —
 * including an explicit `0`, which genuinely means «продать по себестоимости». That distinction is
 * the whole point of the feature, and it drives every decision here:
 *
 *   • INHERITING line → the field is EMPTY and the КП rate shows through as a muted placeholder
 *     (Odoo/CPQ convention). The seller always sees the effective number, never a blank cell, but
 *     the ghost styling says «это не моё значение, оно унаследовано».
 *   • OVERRIDDEN line → the value renders in solid, semibold text and a revert control appears.
 *     The weight contrast IS the at-a-glance «overridden» marker across a 60-line КП (a separate
 *     badge would cost row height, which wave D spent real effort reclaiming); the revert button
 *     doubles as the explicit marker and the one-click way back to inheritance.
 *
 * Clearing the field commits `null` via `onRevert` (see `NumericCell.onClear`) — committing `0`
 * instead would silently reprice the line to cost, which is the single most dangerous confusion in
 * this feature. Both the ✕-clear and the revert button route through the SAME `onRevert`.
 *
 * The gross-margin-on-price figure the old chip displayed is not lost: it stays in the row's detail
 * economics strip and in this cell's tooltip, alongside landed cost and line profit.
 *
 * Memoized (DT4) so a facade re-render that leaves the row's numbers untouched does not re-render
 * every visible margin cell.
 */
const MarginCell: React.FC<MarginCellProps> = React.memo(({
	index, rowId, line, quoteMarginPercent, signal, landedCost, presentationCurrency, readOnly,
	invalid, errorMessage, onCommit, onRevert,
}) => {
	const { t } = useTranslation();
	const isOverridden = line.isMarginOverridden;
	// The placeholder is the number the line actually prices at while it inherits — resolved by the
	// pricing mirror, so it can never drift from the rate the «Сумма» column was computed with.
	const inheritedPercent = Number(quoteMarginPercent ?? 0).toFixed(0);

	return (
		<div className="flex items-center gap-0.5">
			<Tooltip>
				<TooltipTrigger asChild>
					<span className="min-w-0 flex-1">
						<NumericCell
							min={0}
							max={QUOTE_ITEM_MAX_MARGIN_PERCENT}
							maxToastKey="quote.validation.marginTooLarge"
							ariaLabel={t('quote.marginOverride.ariaLabel', { index })}
							placeholder={inheritedPercent}
							// `px-1 min-w-[3rem]` — не косметика: до 14-08 наценка ОБРЕЗАЛАСЬ. Базовый Input даёт
							// `px-3` (24px), а колонка в таблице с авто-раскладкой ужалась до 61px, из которых
							// кнопка отката забирает ~26px — полю оставалось 35px, тексту 11px. Продавец вводил
							// 25 и видел «2»; потолок значения — 500, то есть ТРИ знака. Ширину лечим ЗДЕСЬ, а не
							// классом `w-*` на `<th>`: при `table-layout: auto` браузер такую подсказку игнорирует
							// (проверено — заголовок с `w-32` остался 61px), а min-width содержимого раздвигает
							// колонку. Найдено прогоном клина глазами.
							className={cn(
								'h-8 w-full min-w-[3rem] rounded-none border-none px-1 text-xs tabular-nums shadow-none text-center focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
								isOverridden ? 'font-semibold text-foreground' : 'text-muted-foreground',
							)}
							dataCellRow={rowId}
							dataCellCol="margin_percent"
							disabled={readOnly}
							value={line.isMarginOverridden ? line.effectiveMarginPercent : null}
							invalid={invalid}
							errorMessage={errorMessage}
							onCommit={onCommit}
							onClear={onRevert}
						/>
					</span>
				</TooltipTrigger>
				<TooltipContent>
					<div className="flex flex-col gap-0.5">
						{signal && (
							<>
								<span>{t('quote.economics.landedCost')}: {formatMoney(landedCost, presentationCurrency)}</span>
								<span>{t('quote.lineProfit')}: {formatMoney(signal.profit, presentationCurrency)}</span>
								<span>{t('quote.economics.grossMargin')}: {signal.marginPct.toFixed(1)}%</span>
							</>
						)}
						<span className="mt-0.5 font-medium text-foreground">
							{isOverridden
								? t('quote.marginOverride.overriddenHint', {
									percent: line.effectiveMarginPercent,
									quotePercent: inheritedPercent,
								})
								: t('quote.marginOverride.inheritedHint', { percent: inheritedPercent })}
						</span>
					</div>
				</TooltipContent>
			</Tooltip>
			{/* One-click «вернуть наценку КП». Rendered ONLY on an overridden line, so its presence is
			    itself the override marker — and its absence keeps an inheriting cell visually quiet. */}
			{isOverridden && !readOnly && (
				<Tooltip>
					<TooltipTrigger asChild>
						<Button
							variant="ghost"
							size="icon-xs"
							onClick={onRevert}
							className="shrink-0 text-muted-foreground hover:text-foreground"
							aria-label={t('quote.marginOverride.revertAria', { index })}
						>
							<RotateCcw className="size-3" />
						</Button>
					</TooltipTrigger>
					<TooltipContent>{t('quote.marginOverride.revert')}</TooltipContent>
				</Tooltip>
			)}
		</div>
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
	// Ставки ГТК рядом с полем пошлины: менеджер смотрит и вносит цифру САМ — автоподстановки нет
	// (пошлина зависит от происхождения, преференций и сертификата СТ-1, это его решение).
	const [dutiesOpen, setDutiesOpen] = useState(false);
	const {
		activeQuote, readOnly, econ, canViewCost, showCostColumns, presentationCurrency, currencies,
		pricingMirror, selection, handleFieldChange, cellError, cellErrors, hiddenErrorFields,
		fieldLabel, expandedRowId, toggleRow, setExpandedRowId, fxRateFor, lineCostInPresentation,
		handleDeleteItem, setReassignItemId, rowRefs, mainColCount,
		draftItems, handleMoveRow, handleRenameRow, reorderDisabled, itemsUnderSection, rowPaddingY,
	} = useQuoteBuilderGrid();

	// U5: this ITEM belongs to a SECTION → a light left rule groups it under its heading.
	const isUnderSection = itemsUnderSection.has(item.id);

	// U1: ITEM rows reorder with the SAME ↑/↓ swap SECTION/NOTE rows already use (position swap via
	// the transactional bulk-update, incl. its save-before-move guard for rows with unsaved edits).
	// `index` is the row's place in the FULL document, so the first/last guard stays correct while a
	// filter hides neighbours — and under a filter the buttons disable outright (`reorderDisabled`).
	const isFirstRow = index === 0;
	const isLastRow = index === draftItems.length - 1;

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
				<TableCell className={cn('w-8 min-w-8 px-1 text-center sticky left-0 z-10', rowPaddingY, stickyBg)}>
					<RowSelectCheckbox
						checked={isRowSelected}
						onToggle={(shiftKey) => selection.toggle(item.id, shiftKey)}
						ariaLabel={t('quote.bulk.selectRow', { index: index + 1 })}
					/>
				</TableCell>
				<TableCell className={cn('w-10 min-w-10 px-1 text-center sticky left-8 z-10', rowPaddingY, stickyBg)}>
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
				<TableCell className={cn('w-full px-2', rowPaddingY, stickyBg)}>
					<div className={cn('flex min-w-0 w-full items-center gap-2', isUnderSection && 'ml-1 border-l-2 border-border/60 pl-3')}>
						{isOptional && (
							<Badge variant="outline" className="shrink-0 text-xs font-normal text-muted-foreground">
								{t('quote.optional.badge')}
							</Badge>
						)}
						{/* U3: a name typed WITHOUT picking a catalog match is persisted as the line's own
						    `imported_raw_name` through the same single-item PATCH the SECTION/NOTE inline
						    rename already uses — a КП must be able to carry a line that is not a catalog
						    product. */}
						{readOnly ? (
							<span className="min-w-0 flex-1 truncate px-2 text-sm font-medium" title={item.product_name || item.imported_raw_name}>
								{item.product_name || item.imported_raw_name}
							</span>
						) : (
							<ProductNameCell
								item={item}
								index={index + 1}
								onBrowseCandidates={setReassignItemId}
								onCommitFreeText={handleRenameRow}
							/>
						)}
					</div>
				</TableCell>
				<TableCell className="p-0">
					<NumericCell
						min={1}
						max={QUOTE_ITEM_MAX_QUANTITY}
						maxToastKey="quote.validation.qtyTooLarge"
						maxFractionDigits={0}
						ariaLabel={t('quote.quantity')}
						// `min-w-[3.5rem]` — тот же урок, что у наценки (14-08): при `table-layout: auto`
						// колонка ужимается до 37px и «20» читается как «2C». Ширину раздвигает min-width
						// содержимого, а не класс на <th>. Найдено прогоном клина глазами 17-08.
						className="h-8 min-w-[3.5rem] border-none shadow-none rounded-none text-xs font-semibold text-center focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
						dataCellRow={item.id}
						dataCellCol="quantity"
						disabled={readOnly}
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
											// `min-w-[7rem]` — до 17-08 полю стоимости оставалось 20px (ячейка 100px делилась
											// с селектом валюты): продавец вводил 1 200 000 и НЕ ВИДЕЛ ни одной цифры. Корень
											// тот же, что у наценки 14-08 — `table-layout: auto` игнорирует `w-*` на <th>.
											className="h-8 w-full min-w-[7rem] border-none shadow-none rounded-none text-xs font-mono text-right pr-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
											dataCellRow={item.id}
											dataCellCol="frozen_base_price"
											disabled={readOnly}
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
							<Select value={item.frozen_currency || 'UZS'} disabled={readOnly} onValueChange={(code) => handleFieldChange(item.id, 'frozen_currency', code)}>
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
					<TableCell className="p-0">
						<MarginCell
							index={index + 1}
							rowId={item.id}
							line={mirrorLine}
							quoteMarginPercent={activeQuote?.margin_percent}
							signal={signal}
							landedCost={mirrorLine.landedCost ?? item.landed_cost ?? null}
							presentationCurrency={presentationCurrency}
							readOnly={readOnly}
							invalid={!!cellError(item.id, 'margin_percent')}
							errorMessage={cellError(item.id, 'margin_percent')}
							onCommit={(value) => handleFieldChange(item.id, 'margin_percent', value)}
							// DT1 — THE critical write: reverting to inheritance sends `null`, NOT `0`.
							// `0` is a legitimate override meaning «продать по себестоимости», so writing it
							// here would silently reprice the line to cost on the next save.
							onRevert={() => handleFieldChange(item.id, 'margin_percent', null)}
						/>
					</TableCell>
				)}
				<TableCell className={cn('px-2 text-right pr-4', rowPaddingY)}>
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
					{/* U1: two icon COLUMNS — «опция»/удалить on the left, reorder ↑/↓ on the right. Two
					    columns of two keep the row exactly as tall as before (it was already a 2-row
					    stack), so adding reorder costs no vertical space — which U2 is fighting for. */}
					{!readOnly && (
					<div className="flex items-center justify-center gap-0.5">
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
					{/* U1: reorder an ITEM line. The `title` sits on the WRAPPER because a disabled button
					    swallows pointer events and would never show its own tooltip — under an active
					    filter (`reorderDisabled`) that wrapper explains WHY the arrows are dead. */}
					<div
						className="flex flex-col items-center"
						title={reorderDisabled ? t('quote.row.reorderFilterHint') : undefined}
					>
						<Button
							variant="ghost"
							size="icon-xs"
							disabled={isFirstRow || reorderDisabled}
							onClick={() => handleMoveRow(item.id, 'up')}
							title={reorderDisabled ? undefined : t('quote.row.moveUp')}
							aria-label={t('quote.row.moveUpAria', { index: index + 1 })}
						>
							<ChevronUp className="size-3.5" />
						</Button>
						<Button
							variant="ghost"
							size="icon-xs"
							disabled={isLastRow || reorderDisabled}
							onClick={() => handleMoveRow(item.id, 'down')}
							title={reorderDisabled ? undefined : t('quote.row.moveDown')}
							aria-label={t('quote.row.moveDownAria', { index: index + 1 })}
						>
							<ChevronDown className="size-3.5" />
						</Button>
					</div>
					</div>
					)}
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
									<Tooltip>
										<TooltipTrigger asChild>
											<span className="w-fit cursor-help text-xs text-muted-foreground">{t('quote.hsCode')}</span>
										</TooltipTrigger>
										<TooltipContent>{t('quote.hsCodeHelp')}</TooltipContent>
									</Tooltip>
									{/* T1: автокомплит по справочнику ГТК вместо свободного текста (паттерн Shopify —
									    поле в месте работы). Свободный ввод и bulk-сохранение не меняются. */}
									<div className="flex items-center gap-1">
										<HSCodeField
											dense
											placeholder={t('quote.hsCodePlaceholder')}
											aria-invalid={!!cellError(item.id, 'hs_code') || undefined}
											title={cellError(item.id, 'hs_code')}
											className={cn('min-w-0 flex-1', cellError(item.id, 'hs_code') && '[&_input]:border-destructive [&_input]:ring-1 [&_input]:ring-destructive')}
											value={item.hs_code || ''}
											onChange={(value) => handleFieldChange(item.id, 'hs_code', value)}
										/>
										{(item.hs_code || '').replace(/\D/g, '').length === 10 && (
											<button
												type="button"
												className="shrink-0 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
												aria-label={t('customsDuties.action')}
												title={t('customsDuties.action')}
												onClick={() => setDutiesOpen(true)}
											>
												<Landmark className="h-3.5 w-3.5" aria-hidden="true" />
											</button>
										)}
									</div>
									{dutiesOpen && (
										<CustomsDutiesSheet
											hsCode={(item.hs_code || '').replace(/\D/g, '')}
											hsName={item.product_name ?? ''}
											open
											onOpenChange={setDutiesOpen}
										/>
									)}
								</label>
								{canViewCost && (
									<label className="flex flex-col gap-1">
										<Tooltip>
											<TooltipTrigger asChild>
												<span className="w-fit cursor-help text-xs text-muted-foreground">{t('quote.customsDuty')}</span>
											</TooltipTrigger>
											<TooltipContent>{t('quote.customsDutyHelp')}</TooltipContent>
										</Tooltip>
										<NumericCell
											disabled={readOnly}
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
									<Tooltip>
										<TooltipTrigger asChild>
											<span className="w-fit cursor-help text-xs text-muted-foreground">{t('quote.leadTime')}</span>
										</TooltipTrigger>
										<TooltipContent>{t('quote.leadTimeHelp')}</TooltipContent>
									</Tooltip>
									<NumericCell
										disabled={readOnly}
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
										<Tooltip>
											<TooltipTrigger asChild>
												<span className="w-fit cursor-help text-xs text-muted-foreground">{t('quote.discountPercent')}</span>
											</TooltipTrigger>
											<TooltipContent>{t('quote.discountHelp')}</TooltipContent>
										</Tooltip>
										<NumericCell
											disabled={readOnly}
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
