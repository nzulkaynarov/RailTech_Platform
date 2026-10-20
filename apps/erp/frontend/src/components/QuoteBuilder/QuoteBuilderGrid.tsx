import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useVirtualizer } from '@tanstack/react-virtual';
import {
	useQuoteItems, useUpdateQuoteItem, useCreateQuoteItem, useDeleteQuoteItem, useDeal,
	useBulkUpdateQuoteItems, useBulkCreateQuoteItems, useBulkDeleteQuoteItems,
} from '@/hooks/useCRM';
import type { QuoteItem } from '@/api/crmApi';
import { useCurrencies } from '@/hooks/useMasterData';
import { useMediaQuery } from '@/hooks/use-mobile';
import { cn } from '@/lib/utils';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Tabs, TabsContent } from '@/components/ui/tabs';
import { QuoteChargesSection } from '@/components/CRM/QuoteChargesSection';
import { StickyTotalsBar } from '@/components/QuoteBuilder/StickyTotalsBar';
import { useQuoteDraft } from '@/components/QuoteBuilder/useQuoteDraft';
import { useGridKeyboard } from '@/components/QuoteBuilder/useGridKeyboard';
import { useGridWorkspaceKeys } from '@/components/QuoteBuilder/useGridWorkspaceKeys';
import { usePricingMirror } from '@/components/QuoteBuilder/usePricingMirror';
import { hiddenErrorFields } from '@/components/QuoteBuilder/bulkErrors';
import { useRowSelection } from '@/components/QuoteBuilder/useRowSelection';
import { SelectionToolbar } from '@/components/QuoteBuilder/SelectionToolbar';
import { GenerateQuoteDialog } from '@/components/CRM/GenerateQuoteDialog';
import { VIRTUALIZE_THRESHOLD, GRID_DENSITY_ROW_HEIGHT, GRID_DENSITY_ROW_PADDING, marginToneClass } from '@/components/QuoteBuilder/gridConstants';
import { scrollToRowAndFocusCell } from '@/components/QuoteBuilder/gridScrollFocus';
import { QuoteBuilderGridProvider, type QuoteBuilderGridContextValue } from '@/components/QuoteBuilder/QuoteBuilderGridContext';
import { useQuoteBuilderActions } from '@/components/QuoteBuilder/useQuoteBuilderActions';
import { filterQuoteItems, normalizeFilterQuery } from '@/components/QuoteBuilder/filterItems';
import { collapseHiddenItems, itemsUnderSection } from '@/components/QuoteBuilder/sectionGrouping';
import { useSectionCollapse } from '@/components/QuoteBuilder/useSectionCollapse';
import { BuilderToolbar } from '@/components/QuoteBuilder/BuilderToolbar';
import { GridTable } from '@/components/QuoteBuilder/GridTable';
import { EconomicsRail } from '@/components/QuoteBuilder/EconomicsRail';
import { GridDialogs } from '@/components/QuoteBuilder/GridDialogs';
import { useRailState } from '@/components/QuoteBuilder/useRailState';
import { useGridDensity } from '@/components/QuoteBuilder/useGridDensity';
import { deriveQuoteView, makeFieldLabel } from '@/components/QuoteBuilder/quoteDerived';
import { GridLoadingSkeleton, GridNoQuoteState } from '@/components/QuoteBuilder/GridEmptyStates';
import { useGridEditingState } from '@/components/QuoteBuilder/useGridEditingState';
import { useGridDialogState } from '@/components/QuoteBuilder/useGridDialogState';
import { useGridLifecycle } from '@/components/QuoteBuilder/useGridLifecycle';

/**
 * Стабильная ссылка «позиций пока нет». Пока сделка не загружена, запрос позиций выключен и `data`
 * пуст; подстановка литерала `= []` давала НОВЫЙ массив на каждый рендер, а `useQuoteDraft` держит
 * эффект на `[serverItems]` и каждый раз пишет `setDraftItems(<новый массив>)` — рендер → новый `[]`
 * → эффект… («Maximum update depth exceeded», FIX-44/F-7).
 */
const NO_ITEMS: QuoteItem[] = [];

interface QuoteBuilderGridProps {
	dealId?: number;
	onSave?: () => void;
	/** Lifted so the host page (DealQuotePage) can guard in-app navigation away from unsaved edits. */
	onDirtyChange?: (hasUnsavedChanges: boolean) => void;
	/** Только чтение (нет права править цены или КП не в черновике) — см. `QuoteBuilderGridContextValue.readOnly`. */
	readOnly?: boolean;
}

/**
 * КП конструктор — thin facade/orchestrator (волна 3 split). Owns the top-level hooks, state and
 * derived values, assembles the grid context, and composes the presentational package
 * (BuilderToolbar · GridTable/GridRow · EconomicsRail · StickyTotalsBar). The public export name +
 * path are preserved so importers and the existing test-suite are untouched.
 */
export const QuoteBuilderGrid: React.FC<QuoteBuilderGridProps> = ({ dealId: propDealId, onSave, onDirtyChange, readOnly = false }) => {
	const { t } = useTranslation();
	const dealId = propDealId || 0;

	const { data: deal, isLoading: dealLoading } = useDeal(dealId);
	// Позиции берём у АКТИВНОГО КП, а не у сделки: у сделки бывает несколько документов
	// (контейнер строк заявки покупателя и КП продавца), и фильтр по сделке показывал их
	// вперемешку — 4 строки вместо 2, половина с нулевой ценой, и такое можно было
	// отправить клиенту. Пока активный КП не приехал, запрос не уходит.
	const activeQuoteId = deal?.active_quote?.id;
	const { data: quoteItems = NO_ITEMS, isLoading: itemsLoading } = useQuoteItems(
		activeQuoteId ? { quote: activeQuoteId } : undefined,
	);
	const { data: currencies = [] } = useCurrencies();
	const updateMutation = useUpdateQuoteItem();
	const bulkUpdateMutation = useBulkUpdateQuoteItems();
	const bulkCreateMutation = useBulkCreateQuoteItems();
	const bulkDeleteMutation = useBulkDeleteQuoteItems();
	const createItemMutation = useCreateQuoteItem();
	const deleteItemMutation = useDeleteQuoteItem();

	// Draft state machine (WP-D) + local undo/redo stack (WP-J / U6).
	const { draftItems, dirtyIds, hasUnsavedChanges, setField, applyBulk, clearDirtyAfterSave, undo, canUndo, redo, canRedo } = useQuoteDraft(quoteItems);

	// U4 — «найти в КП». `visibleItems` is what the TABLE renders (and what the virtualizer windows
	// and the keyboard navigates). Everything money-bearing — usePricingMirror, the totals bar, the
	// save payload, section subtotals — keeps reading the FULL `draftItems`, so narrowing the view
	// can never change what the КП is worth or silently drop an edited row from a save.
	const [filterQuery, setFilterQuery] = useState('');
	const isFiltered = normalizeFilterQuery(filterQuery).length > 0;
	// U5 — collapsible sections. `visibleItems` is the U4-filtered list with each COLLAPSED section's
	// children dropped (serverItems → U4 filter → collapse filter → visibleItems). Collapse state is
	// client-only + persisted; it never touches draftItems, the totals or the save payload.
	const { collapsedSections, isSectionCollapsed, toggleSectionCollapse } = useSectionCollapse();
	const visibleItems = useMemo(
		() => collapseHiddenItems(filterQuoteItems(draftItems, filterQuery), collapsedSections),
		[draftItems, filterQuery, collapsedSections],
	);
	// U5 — non-SECTION rows that belong to a SECTION (full-document membership) → left-indent cue.
	const underSectionIds = useMemo(() => itemsUnderSection(draftItems), [draftItems]);
	// Original 1-based document position per row id — the grid keeps numbering lines by their place
	// in the КП, so a filtered view shows «12.» not «1.» (and delete/select aria-labels stay true).
	const documentIndexById = useMemo(() => {
		const map = new Map<number, number>();
		draftItems.forEach((item, position) => map.set(item.id, position));
		return map;
	}, [draftItems]);

	// Row multi-select (WP-J): pruning follows the FULL row set (a filtered-out row keeps its
	// selection), while «выбрать все» / Shift-range act on the VISIBLE subset only (U4).
	const selection = useRowSelection(
		draftItems.map((item) => item.id),
		visibleItems.map((item) => item.id),
	);

	// Windowed (virtualized) line rendering above the threshold (волна 3). The virtualizer always runs
	// (Rules of Hooks) but only drives layout when `shouldVirtualize` — small КП render every row.
	// U4: it counts the VISIBLE rows, so a filtered set windows correctly instead of reserving space
	// for rows that are not in the DOM.
	const scrollContainerRef = useRef<HTMLDivElement>(null);
	const shouldVirtualize = visibleItems.length > VIRTUALIZE_THRESHOLD;
	// U7 — row density (comfortable/compact). The estimateSize below MUST track it, so the virtualizer
	// seeds off-screen rows with the height they will actually render at in the current density.
	const { gridDensity, toggleGridDensity } = useGridDensity();
	const rowPaddingY = GRID_DENSITY_ROW_PADDING[gridDensity];
	const rowEstimateSize = GRID_DENSITY_ROW_HEIGHT[gridDensity];
	const virtualizer = useVirtualizer({
		count: visibleItems.length,
		getScrollElement: () => scrollContainerRef.current,
		estimateSize: () => rowEstimateSize,
		overscan: 8,
		getItemKey: (index) => visibleItems[index]?.id ?? index,
	});
	// Flipping density changes every row's real height; re-measure so the cached measurements (and the
	// scrollbar) recompute off the new estimate instead of holding the old per-row heights.
	useEffect(() => {
		virtualizer.measure();
	}, [gridDensity, virtualizer]);

	// Keyboard nav across the window edge: scroll the target row in, then focus its cell (волна 3).
	const focusCellAtRow = (rowIndex: number, column: string) => {
		const targetId = visibleItems[rowIndex]?.id;
		if (targetId == null) return;
		scrollToRowAndFocusCell(rowIndex, targetId, column, {
			scrollToIndex: (index) => virtualizer.scrollToIndex(index, { align: 'auto' }),
			getContainer: () => scrollContainerRef.current,
		});
	};
	// Excel-style keyboard navigation (WP-G) — virtualization-aware only while windowed. S1: a
	// windowed ArrowUp/Down skips SECTION/NOTE rows (no navigable cell) via `isNavigable`.
	const gridKeyboard = useGridKeyboard(
		shouldVirtualize
			? {
				rowIds: visibleItems.map((item) => item.id),
				focusCellAtRow,
				isNavigable: (rowId) => (visibleItems.find((item) => item.id === rowId)?.display_type ?? 'ITEM') === 'ITEM',
			}
			: undefined,
	);

	// Редактирование строк: ошибки ячеек, поля добавления, состояние Excel-вставки.
	const editing = useGridEditingState({ setField, t });
	const {
		cellErrors, setCellErrors, cellError, handleFieldChange,
		newItemName, setNewItemName, newItemQty, setNewItemQty, newItemPrice, setNewItemPrice,
		showAddRow, setShowAddRow,
		pasteOpen, setPasteOpen, pasteText, setPasteText, pasteRowErrors, setPasteRowErrors,
		addNameRef, addRowRef, rowRefs,
	} = editing;

	// Live local pricing mirror (P0-2) — null-safe off deal?.active_quote (called unconditionally).
	const mirrorQuote = deal?.active_quote ?? null;
	const mirrorEcon = mirrorQuote?.economics ?? null;
	const pricingMirror = usePricingMirror({
		draftItems,
		dirtyIds,
		marginPercent: mirrorQuote?.margin_percent,
		vatRate: mirrorQuote?.vat_rate || '12',
		fxSnapshot: mirrorQuote?.fx_snapshot ?? {},
		fxManual: mirrorQuote?.fx_manual ?? {},
		fxMarket: mirrorQuote?.fx_market ?? {},
		charges: mirrorQuote?.charges ?? [],
		canViewCost: !!mirrorEcon,
		minMarginPercent: mirrorEcon ? Number(mirrorEcon.min_margin_percent) : null,
		serverTotals: {
			subtotalExclVat: mirrorQuote?.subtotal_excl_vat,
			chargesTotal: mirrorQuote?.charges_total,
			vatAmount: mirrorQuote?.vat_amount,
			totalInclVat: mirrorQuote?.total_incl_vat,
			grossMarginPercent: mirrorEcon ? Number(mirrorEcon.gross_margin_percent) : null,
		},
	});
	const mirrorTotals = pricingMirror.totals;

	// UI-состояние: диалоги, режимы, «занятость». Не влияет на draftItems.
	const dialogs = useGridDialogState();
	const {
		showAiMatch, setShowAiMatch, importOpen, setImportOpen, showGenerateQuote, setShowGenerateQuote,
		showSettings, setShowSettings, pricingBusy, setPricingBusy, draftBusy, setDraftBusy,
		expandedRowId, setExpandedRowId, toggleRow, activeTab, setActiveTab, fullscreen, setFullscreen,
		deleteTarget, setDeleteTarget, reassignItemId, setReassignItemId,
		conflictOpen, setConflictOpen, conflictIds, setConflictIds,
	} = dialogs;

	// Возврат с вкладки «Начисления и скидки» ОСТАВЛЯЛ ТАБЛИЦУ ПУСТОЙ (60 позиций → 0 строк):
	// Radix размонтирует содержимое неактивной вкладки, вместе с ним уходит контейнер прокрутки,
	// а виртуализатор об этом не узнаёт — новый узел появляется ПОСЛЕ рендера родителя, и без
	// повторного замера окно остаётся нулевым. Продавец возвращался к своему КП и видел одну
	// шапку без единой строки, без объяснения. Найдено прогоном глазами 19-08.
	// `useLayoutEffect` — чтобы пересчёт случился до отрисовки и пустой кадр не мелькнул.
	useLayoutEffect(() => {
		if (activeTab === 'items') virtualizer.measure();
	}, [activeTab, virtualizer]);

	// Economics-rail view state (open/collapsed persisted, inline-aside-vs-slide-over Sheet).
	const { railAsSheet, railOpen, railSheetOpen, setRailSheetOpen, toggleRail } = useRailState();
	// Below 1200px the cost columns drop out of the main table (economics stay in the row detail).
	const isCompact = useMediaQuery('(max-width: 1199px)');


	// All mutation-driven actions (save · add · paste · delete · bulk · pricing · AI draft).
	const actions = useQuoteBuilderActions({
		dealId, deal, draftItems, dirtyIds, selection, isCompact,
		updateMutation, bulkUpdateMutation, bulkCreateMutation, bulkDeleteMutation, createItemMutation, deleteItemMutation,
		applyBulk, clearDirtyAfterSave,
		newItemName, newItemQty, newItemPrice, deleteTarget,
		setCellErrors, setExpandedRowId, setNewItemName, setNewItemQty, setNewItemPrice,
		setPasteText, setPasteRowErrors, setPasteOpen, setDeleteTarget, setPricingBusy, setDraftBusy,
		setConflictIds, setConflictOpen,
		addNameRef, addRowRef, rowRefs, onSave,
	});

	// Esc-выход из фокус-режима + две страховки от потери несохранённых правок.
	useGridLifecycle({ fullscreen, setFullscreen, hasUnsavedChanges, onDirtyChange });

	// U6 working-area keyboard shortcuts (copy-out TSV + local draft undo/redo) — extracted hook.
	const { handleWorkspaceKeyDown } = useGridWorkspaceKeys({
		draftItems, selection, undo, redo, canUndo, canRedo,
	});

	if (itemsLoading || dealLoading) return <GridLoadingSkeleton />;

	const activeQuote = deal?.active_quote;

	// Нет активного КП → экран с первичным действием, открывающим создание КП (Q1: не тупик).
	if (!activeQuote) {
		return (
			<>
				<GridNoQuoteState
					dealId={dealId}
					draftBusy={draftBusy}
					onGenerateDraft={actions.handleGenerateDraft}
					onOpenGenerateDialog={() => setShowGenerateQuote(true)}
				/>
				<GenerateQuoteDialog dealId={dealId || null} open={showGenerateQuote} onOpenChange={setShowGenerateQuote} />
			</>
		);
	}

	// Производные от активного КП: валюта/НДС, гейт себестоимости, курсы, число колонок.
	const {
		presentationCurrency, vatRate, econ, canViewCost, showCostColumns,
		effectiveLeadTime, mainColCount, fxRateFor, lineCostInPresentation,
	} = deriveQuoteView(activeQuote, isCompact);
	const fieldLabel = makeFieldLabel(t);

	const contextValue: QuoteBuilderGridContextValue = {
		activeQuote, readOnly, econ, canViewCost, showCostColumns, presentationCurrency, vatRate, effectiveLeadTime,
		currencies, mainColCount, draftItems, pricingMirror, mirrorTotals, selection,
		visibleItems, documentIndexById, filterQuery, setFilterQuery, isFiltered,
		handleFieldChange, cellError, cellErrors, hiddenErrorFields, fieldLabel,
		expandedRowId, toggleRow, setExpandedRowId,
		isSectionCollapsed, toggleSectionCollapse, itemsUnderSection: underSectionIds,
		fxRateFor, lineCostInPresentation,
		handleDeleteItem: actions.handleDeleteItem, setReassignItemId, rowRefs,
		handleMoveRow: actions.handleMoveRow, handleRenameRow: actions.handleRenameRow,
		// U1/U4: ↑/↓ swap positions with the adjacent row of the FULL document — meaningless (and
		// surprising) while the visible set is filtered, so the controls disable with a tooltip.
		reorderDisabled: isFiltered,
		showAddRow, setShowAddRow, handleAddSection: actions.handleAddSection, handleAddNote: actions.handleAddNote,
		openPasteDialog: actions.openPasteDialog, openImportDialog: () => setImportOpen(true), setShowAiMatch,
		handlePricingAssist: actions.handlePricingAssist, pricingBusy, fullscreen, setFullscreen, setShowSettings,
		railAsSheet, railOpen, railSheetOpen, setRailSheetOpen, toggleRail,
		scrollContainerRef, gridKeyboardOnKeyDown: gridKeyboard.onKeyDown, handleGridPaste: readOnly ? () => {} : actions.handleGridPaste,
		virtualizer, shouldVirtualize,
		activeTab,
		gridDensity, toggleGridDensity, rowPaddingY,
		newItemName, setNewItemName, newItemQty, setNewItemQty, newItemPrice, setNewItemPrice,
		handleAddItem: actions.handleAddItem, addNameRef, addRowRef, createItemPending: createItemMutation.isPending,
	};

	return (
		<TooltipProvider>
			<QuoteBuilderGridProvider value={contextValue}>
				<div
					className={cn(
						'flex flex-col min-h-0 gap-1.5',
						// Focus (fullscreen) mode: the grid takes over the whole viewport; Esc / ⛶ exits.
						fullscreen ? 'fixed inset-0 z-50 bg-background p-3' : 'h-full',
					)}
					onKeyDown={handleWorkspaceKeyDown}
				>
					{/* U2: ONE toolbar row owns the tabs, the row actions (or the bulk-action strip while
					    rows are selected), the «найти в КП» filter and the view controls. The tabs used to
					    sit on their own line and the selection strip stacked a second full-width strip —
					    together ~90px of chrome that now costs 0. `<Tabs>` wraps the toolbar so `TabsList`
					    can live inside it while `TabsContent` stays below. */}
					<Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'items' | 'charges')} className="flex flex-1 flex-col min-h-0 gap-1.5">
						<BuilderToolbar
							selectionSlot={selection.count > 0 ? (
								<SelectionToolbar
									count={selection.count}
									onDelete={actions.handleBulkDelete}
									onApplyDiscount={actions.handleBulkDiscount}
									onApplyPriceChange={actions.handleBulkPriceChange}
									onDuplicate={actions.handleBulkDuplicate}
									onClear={selection.clear}
									deleting={bulkDeleteMutation.isPending}
									duplicating={bulkCreateMutation.isPending}
								/>
							) : undefined}
						/>

						{/* Working area: the active tab's panel on the left, economics rail on the right */}
						<div className="flex flex-1 min-h-0 gap-3">
							<div className="flex flex-col flex-1 min-w-0 min-h-0">
								<TabsContent value="items" className="flex flex-1 flex-col min-h-0 mt-0 overflow-hidden">
									<GridTable />
								</TabsContent>

								{/* КП-level expense items / discounts (seller-only) — its own tab. */}
								<TabsContent value="charges" className="flex-1 min-h-0 overflow-auto mt-0">
									{activeQuote && <QuoteChargesSection quoteId={activeQuote.id} currency={presentationCurrency} readOnly={readOnly} />}
								</TabsContent>
							</div>

							<EconomicsRail />
						</div>
					</Tabs>

					{/* Sticky totals footer — always in view. Total + margin come from the live mirror. */}
					<StickyTotalsBar
						positionsCount={draftItems.length}
						canViewCost={canViewCost}
						marginPercent={mirrorTotals.grossMarginPercent ?? (econ ? Number(econ.gross_margin_percent) : undefined)}
						marginTone={econ
							? marginToneClass(
								econ.below_cost || econ.below_floor,
								mirrorTotals.grossMarginPercent ?? Number(econ.gross_margin_percent),
								Number(econ.target_margin_percent),
							)
							: undefined}
						totalInclVat={mirrorTotals.totalInclVat}
						currency={presentationCurrency}
						readOnly={readOnly}
						onOpenEconomics={railAsSheet ? () => setRailSheetOpen(true) : undefined}
						hasUnsavedChanges={hasUnsavedChanges}
						saving={bulkUpdateMutation.isPending}
						onSave={actions.handleSave}
						onUndo={undo}
						canUndo={canUndo}
						onRedo={redo}
						canRedo={canRedo}
					/>

					<GridDialogs
						pasteOpen={pasteOpen}
						setPasteOpen={setPasteOpen}
						pasteText={pasteText}
						pasteRowErrors={pasteRowErrors}
						setPasteRowErrors={setPasteRowErrors}
						pasteSubmitting={bulkCreateMutation.isPending}
						onPasteConfirm={actions.handlePasteConfirm}
						showAiMatch={showAiMatch}
						setShowAiMatch={setShowAiMatch}
						draftItems={draftItems}
						importOpen={importOpen}
						setImportOpen={setImportOpen}
						activeQuote={activeQuote}
						showSettings={showSettings}
						setShowSettings={setShowSettings}
						reassignItemId={reassignItemId}
						setReassignItemId={setReassignItemId}
						deleteTarget={deleteTarget}
						setDeleteTarget={setDeleteTarget}
						onConfirmDelete={actions.confirmDeleteItem}
						deletePending={deleteItemMutation.isPending}
						conflictOpen={conflictOpen}
						setConflictOpen={setConflictOpen}
						conflictIds={conflictIds}
						setConflictIds={setConflictIds}
						clearDirtyAfterSave={clearDirtyAfterSave}
						setCellErrors={setCellErrors}
					/>
				</div>
			</QuoteBuilderGridProvider>
		</TooltipProvider>
	);
};
