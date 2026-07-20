import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Loader2, Sparkles, FileText } from 'lucide-react';
import { QuoteItem, QuoteEconomics } from '@/api/crmApi';
import {
	useQuoteItems, useUpdateQuoteItem, useCreateQuoteItem, useDeleteQuoteItem, useDeal,
	useBulkUpdateQuoteItems, useBulkCreateQuoteItems, useBulkDeleteQuoteItems,
} from '@/hooks/useCRM';
import { useCurrencies } from '@/hooks/useMasterData';
import { useMediaQuery } from '@/hooks/use-mobile';
import { cn } from '@/lib/utils';
import { toDecimal } from '@/utils/decimal';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Tabs, TabsContent } from '@/components/ui/tabs';
import {
	AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
	AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { QuoteChargesSection } from '@/components/CRM/QuoteChargesSection';
import { StickyTotalsBar } from '@/components/QuoteBuilder/StickyTotalsBar';
import { useQuoteDraft, type DraftFieldValue } from '@/components/QuoteBuilder/useQuoteDraft';
import { useGridKeyboard } from '@/components/QuoteBuilder/useGridKeyboard';
import { usePricingMirror } from '@/components/QuoteBuilder/usePricingMirror';
import { cellErrorKey, hiddenErrorFields } from '@/components/QuoteBuilder/bulkErrors';
import { ExcelPasteDialog } from '@/components/QuoteBuilder/ExcelPasteDialog';
import { useRowSelection } from '@/components/QuoteBuilder/useRowSelection';
import { SelectionToolbar } from '@/components/QuoteBuilder/SelectionToolbar';
import { AICatalogMatchDialog } from '@/components/Admin/AICatalogMatchDialog';
import { GenerateQuoteDialog } from '@/components/CRM/GenerateQuoteDialog';
import { QuoteSettingsDialog } from '@/components/CRM/QuoteSettingsDialog';
import { ReassignProductDialog } from '@/components/CRM/ReassignProductDialog';
import { QUOTE_ITEMS_BULK_MAX_ROWS, VIRTUALIZE_THRESHOLD, marginToneClass } from '@/components/QuoteBuilder/gridConstants';
import { scrollToRowAndFocusCell } from '@/components/QuoteBuilder/gridScrollFocus';
import { QuoteBuilderGridProvider, type QuoteBuilderGridContextValue } from '@/components/QuoteBuilder/QuoteBuilderGridContext';
import { useQuoteBuilderActions } from '@/components/QuoteBuilder/useQuoteBuilderActions';
import { filterQuoteItems, normalizeFilterQuery } from '@/components/QuoteBuilder/filterItems';
import { BuilderToolbar } from '@/components/QuoteBuilder/BuilderToolbar';
import { GridTable } from '@/components/QuoteBuilder/GridTable';
import { EconomicsRail } from '@/components/QuoteBuilder/EconomicsRail';

interface QuoteBuilderGridProps {
	dealId?: number;
	onSave?: () => void;
	/** Lifted so the host page (DealQuotePage) can guard in-app navigation away from unsaved edits. */
	onDirtyChange?: (hasUnsavedChanges: boolean) => void;
}

/**
 * КП конструктор — thin facade/orchestrator (волна 3 split). Owns the top-level hooks, state and
 * derived values, assembles the grid context, and composes the presentational package
 * (BuilderToolbar · GridTable/GridRow · EconomicsRail · StickyTotalsBar). The public export name +
 * path are preserved so importers and the existing test-suite are untouched.
 */
export const QuoteBuilderGrid: React.FC<QuoteBuilderGridProps> = ({ dealId: propDealId, onSave, onDirtyChange }) => {
	const { t } = useTranslation();
	const dealId = propDealId || 0;

	const { data: quoteItems = [], isLoading: itemsLoading } = useQuoteItems({ deal_id: dealId });
	const { data: deal, isLoading: dealLoading } = useDeal(dealId);
	const { data: currencies = [] } = useCurrencies();
	const updateMutation = useUpdateQuoteItem();
	const bulkUpdateMutation = useBulkUpdateQuoteItems();
	const bulkCreateMutation = useBulkCreateQuoteItems();
	const bulkDeleteMutation = useBulkDeleteQuoteItems();
	const createItemMutation = useCreateQuoteItem();
	const deleteItemMutation = useDeleteQuoteItem();

	// Draft state machine (WP-D) + local undo stack (WP-J).
	const { draftItems, dirtyIds, hasUnsavedChanges, setField, applyBulk, clearDirtyAfterSave, undo, canUndo } = useQuoteDraft(quoteItems);

	// U4 — «найти в КП». `visibleItems` is what the TABLE renders (and what the virtualizer windows
	// and the keyboard navigates). Everything money-bearing — usePricingMirror, the totals bar, the
	// save payload, section subtotals — keeps reading the FULL `draftItems`, so narrowing the view
	// can never change what the КП is worth or silently drop an edited row from a save.
	const [filterQuery, setFilterQuery] = useState('');
	const isFiltered = normalizeFilterQuery(filterQuery).length > 0;
	const visibleItems = useMemo(() => filterQuoteItems(draftItems, filterQuery), [draftItems, filterQuery]);
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
	const virtualizer = useVirtualizer({
		count: visibleItems.length,
		getScrollElement: () => scrollContainerRef.current,
		estimateSize: () => 44,
		overscan: 8,
		getItemKey: (index) => visibleItems[index]?.id ?? index,
	});

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

	// Per-cell rejection codes from the LAST bulk save (P0-4), keyed `${id}:${field}` → CODE.
	const [cellErrors, setCellErrors] = useState<Record<string, string>>({});
	const [newItemName, setNewItemName] = useState('');
	const [newItemQty, setNewItemQty] = useState<string>('1');
	const [newItemPrice, setNewItemPrice] = useState<string>('0');
	const [showAddRow, setShowAddRow] = useState(false);
	const [pasteOpen, setPasteOpen] = useState(false);
	const [pasteText, setPasteText] = useState('');
	const [pasteRowErrors, setPasteRowErrors] = useState<Record<number, Record<string, string>>>({});
	const addNameRef = useRef<HTMLInputElement>(null);
	const addRowRef = useRef<HTMLTableRowElement>(null);
	const rowRefs = useRef<Map<number, HTMLTableRowElement>>(new Map());

	// Edit a line AND drop any stale bulk-save error on that exact cell.
	const handleFieldChange = (id: number, field: keyof QuoteItem, value: DraftFieldValue) => {
		setField(id, field, value);
		const key = cellErrorKey(id, field as string);
		if (cellErrors[key]) {
			setCellErrors((previous) => {
				const next = { ...previous };
				delete next[key];
				return next;
			});
		}
	};

	// Localized message for a rejected cell (or undefined when the cell is clean).
	const cellError = (id: number, field: string): string | undefined => {
		const code = cellErrors[cellErrorKey(id, field)];
		if (!code) return undefined;
		const key = `quote.validation.${code}`;
		const label = t(key);
		return label === key ? code : label; // unlocalized new code → show the raw code
	};

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

	const [showAiMatch, setShowAiMatch] = useState(false);
	const [showGenerateQuote, setShowGenerateQuote] = useState(false);
	const [showSettings, setShowSettings] = useState(false);
	const [pricingBusy, setPricingBusy] = useState(false);
	const [draftBusy, setDraftBusy] = useState(false);

	// UI-only state — deliberately kept OUT of draftItems so it never trips hasUnsavedChanges.
	const [expandedRowId, setExpandedRowId] = useState<number | null>(null);
	const [railOpen, setRailOpen] = useState<boolean>(() => {
		try {
			const saved = localStorage.getItem('kp.rail.open');
			if (saved !== null) return saved !== 'false'; // an explicit user toggle always wins
			// Default: open on wide screens, COLLAPSED on laptops (≤~1400px) so the fixed 320px rail
			// doesn't squeeze the line table into truncation/overflow (audit A1).
			return typeof window === 'undefined' || window.innerWidth >= 1400;
		} catch { return true; }
	});
	const toggleRail = () => {
		setRailOpen((open) => {
			const next = !open;
			try { localStorage.setItem('kp.rail.open', String(next)); } catch { /* private mode */ }
			return next;
		});
	};

	// Below xl the rail becomes a slide-over Sheet; ≥xl it stays the inline collapsible <aside>.
	const railAsSheet = useMediaQuery('(max-width: 1279px)');
	const [railSheetOpen, setRailSheetOpen] = useState(false);
	// Below 1200px the cost columns drop out of the main table (economics stay in the row detail).
	const isCompact = useMediaQuery('(max-width: 1199px)');

	const [activeTab, setActiveTab] = useState<'items' | 'charges'>('items');
	const [fullscreen, setFullscreen] = useState(false);
	const [deleteTarget, setDeleteTarget] = useState<number | null>(null);
	// Manual product attach/re-match for a КП line (human counterpart to AI-подбор).
	const [reassignItemId, setReassignItemId] = useState<number | null>(null);

	// Optimistic-lock conflict dialog (волна 3): a save that lost a race to a colleague opens this
	// instead of writing. `conflictIds` are the stale rows — only the versioned bulk save opens the
	// dialog, and it always passes a non-empty set (pricing-assist carries no version, so it can't
	// 409). No empty-ids "reset all" case exists.
	const queryClient = useQueryClient();
	const [conflictOpen, setConflictOpen] = useState(false);
	const [conflictIds, setConflictIds] = useState<number[]>([]);
	// «Обновить»: consciously drop the local edits on the conflicting rows, then refetch quote-items
	// so the fresh server values re-merge. The seller's stale edits to the conflicting lines are
	// replaced by the colleague's committed values (spec §5.3).
	const handleConflictRefresh = () => {
		const idsToReset = conflictIds;
		clearDirtyAfterSave(idsToReset);
		setCellErrors((previous) => {
			const next = { ...previous };
			for (const key of Object.keys(next)) {
				if (idsToReset.includes(Number(key.split(':')[0]))) delete next[key];
			}
			return next;
		});
		queryClient.invalidateQueries({ queryKey: ['quote-items'] });
		queryClient.invalidateQueries({ queryKey: ['deals'] });
		setConflictOpen(false);
		setConflictIds([]);
		toast.info(t('quote.conflict.refreshed'));
	};

	const toggleRow = (id: number) => setExpandedRowId((current) => (current === id ? null : id));

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

	// Esc exits focus mode (mirrors the ⛶ toggle) — a layered dialog owns its own Escape.
	useEffect(() => {
		if (!fullscreen) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key !== 'Escape') return;
			if (event.defaultPrevented || document.querySelector('[role="dialog"], [role="alertdialog"]')) return;
			setFullscreen(false);
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, [fullscreen]);

	// Lift the unsaved-changes signal so the host page can guard in-app navigation (Back button).
	useEffect(() => {
		onDirtyChange?.(hasUnsavedChanges);
	}, [hasUnsavedChanges, onDirtyChange]);

	// Browser-level guard: warn before a tab close / reload while there are unsaved edits.
	useEffect(() => {
		if (!hasUnsavedChanges) return;
		const handleBeforeUnload = (event: BeforeUnloadEvent) => {
			event.preventDefault();
			event.returnValue = '';
		};
		window.addEventListener('beforeunload', handleBeforeUnload);
		return () => window.removeEventListener('beforeunload', handleBeforeUnload);
	}, [hasUnsavedChanges]);

	// Ctrl/Cmd+Z reverts the last local draft edit (WP-J undo) — but not inside a text input.
	const handleWorkspaceKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
		if (!(event.ctrlKey || event.metaKey) || event.shiftKey) return;
		if (event.key !== 'z' && event.key !== 'Z') return;
		const target = event.target as HTMLElement;
		if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable) return;
		if (!canUndo) return;
		event.preventDefault();
		undo();
	};

	if (itemsLoading || dealLoading) {
		return (
			<Card className="min-h-[200px]">
				<CardContent className="flex flex-col items-center justify-center gap-4 py-12">
					<Skeleton className="h-8 w-full max-w-md" />
					<Skeleton className="h-6 w-full max-w-lg" />
					<Skeleton className="h-6 w-full max-w-lg" />
					<Skeleton className="h-6 w-full max-w-lg" />
					<Skeleton className="h-6 w-3/4 max-w-sm" />
				</CardContent>
			</Card>
		);
	}

	const activeQuote = deal?.active_quote;

	// No active quote → guided empty-state with a primary action that opens the КП-creation flow.
	if (!activeQuote) {
		return (
			<>
				<Card className="min-h-[200px]">
					<CardContent className="flex flex-col items-center justify-center gap-3 py-12 text-center">
						<div className="flex size-12 items-center justify-center rounded-full bg-muted">
							<FileText className="size-6 text-muted-foreground" aria-hidden="true" />
						</div>
						<h3 className="text-base font-semibold">{t('quote.empty.title')}</h3>
						<p className="max-w-sm text-sm text-muted-foreground">{t('quote.empty.description')}</p>
						<div className="mt-2 flex flex-wrap items-center justify-center gap-2">
							<Button onClick={actions.handleGenerateDraft} disabled={!dealId || draftBusy}>
								{draftBusy ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" aria-hidden="true" />}
								{t('aiDraft.action')}
							</Button>
							<Button variant="outline" onClick={() => setShowGenerateQuote(true)} disabled={!dealId}>
								<FileText className="size-4" aria-hidden="true" />
								{t('quote.empty.action')}
							</Button>
						</div>
					</CardContent>
				</Card>
				<GenerateQuoteDialog dealId={dealId || null} open={showGenerateQuote} onOpenChange={setShowGenerateQuote} />
			</>
		);
	}

	// Presentation currency (all STORED totals are in UZS); computed columns render in it.
	const presentationCurrency = activeQuote?.quote_currency || 'UZS';
	const vatRate = activeQuote?.vat_rate || '12';

	// Cost-viewer gate: the server redacts cost fields + returns economics === null without
	// quote.view_cost_margin. One derived flag drives every cost-bearing column/panel.
	const econ: QuoteEconomics | null = activeQuote.economics ?? null;
	const canViewCost = !!econ;
	// Viewport gate layered on top: on narrow laptops (<1200px) the two cost columns collapse.
	const showCostColumns = canViewCost && !isCompact;

	// FX rate (сум per 1 unit) for a line cost currency: manual override wins over the frozen snapshot.
	const fxSnapshot = activeQuote?.fx_snapshot ?? {};
	const fxManual = activeQuote?.fx_manual ?? {};
	const fxMarket = activeQuote?.fx_market ?? {};
	const fxRateFor = (code?: string): string => {
		const ccy = (code || 'UZS').toUpperCase();
		if (ccy === 'UZS') return '1';
		return fxManual[ccy] || fxSnapshot[ccy] || fxMarket[ccy] || '1';
	};
	// The line's COST shown in the presentation (UZS) currency, for the tooltip.
	const lineCostInPresentation = (item: QuoteItem): string => {
		const native = toDecimal(item.frozen_base_price).plus(toDecimal(item.customs_duty));
		return native.mul(toDecimal(fxRateFor(item.frozen_currency))).toString();
	};

	// КП срок поставки (до N дн.) — backend-computed effective value.
	const effectiveLeadTime = activeQuote?.effective_delivery_lead_time_days ?? 0;

	// Visible main-row columns (for the detail row + spacer colSpan): select, chevron, name, qty,
	// [base], [margin], sum, delete. Tracks the two cost columns the <1200px gate hides.
	const mainColCount = showCostColumns ? 8 : 6;

	// Human label for a КП-line field code — names the hidden field(s) in the row error marker tooltip.
	const fieldLabel = (field: string): string => {
		const labels: Record<string, string> = {
			customs_duty: t('quote.customsDuty'),
			discount_percent: t('quote.discountPercent'),
			lead_time_days: t('quote.leadTime'),
			hs_code: t('quote.hsCode'),
			frozen_base_price: t('quote.basePrice'),
			frozen_currency: t('quote.lineCurrency'),
			margin_percent: t('quote.marginOverride.header'),
		};
		return labels[field] ?? field;
	};

	const contextValue: QuoteBuilderGridContextValue = {
		activeQuote, econ, canViewCost, showCostColumns, presentationCurrency, vatRate, effectiveLeadTime,
		currencies, mainColCount, draftItems, pricingMirror, mirrorTotals, selection,
		visibleItems, documentIndexById, filterQuery, setFilterQuery, isFiltered,
		handleFieldChange, cellError, cellErrors, hiddenErrorFields, fieldLabel,
		expandedRowId, toggleRow, setExpandedRowId,
		fxRateFor, lineCostInPresentation,
		handleDeleteItem: actions.handleDeleteItem, setReassignItemId, rowRefs,
		handleMoveRow: actions.handleMoveRow, handleRenameRow: actions.handleRenameRow,
		// U1/U4: ↑/↓ swap positions with the adjacent row of the FULL document — meaningless (and
		// surprising) while the visible set is filtered, so the controls disable with a tooltip.
		reorderDisabled: isFiltered,
		showAddRow, setShowAddRow, handleAddSection: actions.handleAddSection, handleAddNote: actions.handleAddNote,
		openPasteDialog: actions.openPasteDialog, setShowAiMatch,
		handlePricingAssist: actions.handlePricingAssist, pricingBusy, fullscreen, setFullscreen, setShowSettings,
		railAsSheet, railOpen, railSheetOpen, setRailSheetOpen, toggleRail,
		scrollContainerRef, gridKeyboardOnKeyDown: gridKeyboard.onKeyDown, handleGridPaste: actions.handleGridPaste,
		virtualizer, shouldVirtualize,
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
									{activeQuote && <QuoteChargesSection quoteId={activeQuote.id} currency={presentationCurrency} />}
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
						hasUnsavedChanges={hasUnsavedChanges}
						saving={bulkUpdateMutation.isPending}
						onSave={actions.handleSave}
						onUndo={undo}
						canUndo={canUndo}
					/>

					<ExcelPasteDialog
						open={pasteOpen}
						onOpenChange={(open) => {
							setPasteOpen(open);
							if (!open) setPasteRowErrors({});
						}}
						initialText={pasteText}
						maxRows={QUOTE_ITEMS_BULK_MAX_ROWS}
						submitting={bulkCreateMutation.isPending}
						rowErrors={pasteRowErrors}
						onConfirm={actions.handlePasteConfirm}
					/>
					<AICatalogMatchDialog open={showAiMatch} onOpenChange={setShowAiMatch} items={draftItems} />
					<QuoteSettingsDialog quote={activeQuote} open={showSettings} onOpenChange={setShowSettings} />
					<ReassignProductDialog
						quoteItemId={reassignItemId}
						open={reassignItemId != null}
						onOpenChange={(o) => !o && setReassignItemId(null)}
					/>

					<AlertDialog open={deleteTarget != null} onOpenChange={(o) => !o && setDeleteTarget(null)}>
						<AlertDialogContent>
							<AlertDialogHeader>
								<AlertDialogTitle>{t('quote.deleteItem')}</AlertDialogTitle>
								<AlertDialogDescription>{t('deleteConfirmations.quoteItemDescription')}</AlertDialogDescription>
							</AlertDialogHeader>
							<AlertDialogFooter>
								<AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
								<AlertDialogAction onClick={actions.confirmDeleteItem} disabled={deleteItemMutation.isPending}>
									{t('common.delete')}
								</AlertDialogAction>
							</AlertDialogFooter>
						</AlertDialogContent>
					</AlertDialog>

					{/* Optimistic-lock conflict (волна 3): a colleague saved these lines first. This isn't a
					    fixable input error — the seller reloads the fresh values, replacing their stale edits. */}
					<AlertDialog open={conflictOpen} onOpenChange={(o) => !o && setConflictOpen(false)}>
						<AlertDialogContent>
							<AlertDialogHeader>
								<AlertDialogTitle>{t('quote.conflict.title')}</AlertDialogTitle>
								<AlertDialogDescription>{t('quote.conflict.description')}</AlertDialogDescription>
							</AlertDialogHeader>
							<AlertDialogFooter>
								<AlertDialogAction onClick={handleConflictRefresh}>
									{t('quote.conflict.refresh')}
								</AlertDialogAction>
							</AlertDialogFooter>
						</AlertDialogContent>
					</AlertDialog>
				</div>
			</QuoteBuilderGridProvider>
		</TooltipProvider>
	);
};
