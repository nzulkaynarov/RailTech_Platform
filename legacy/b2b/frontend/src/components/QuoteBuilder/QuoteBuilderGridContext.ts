import { createContext, useContext } from 'react';
import type { Dispatch, SetStateAction, RefObject, MutableRefObject, ClipboardEvent, KeyboardEvent } from 'react';
import type { Virtualizer } from '@tanstack/react-virtual';
import type { GridDensity } from './gridConstants';
import type { Quote, QuoteItem, QuoteEconomics } from '@/api/crmApi';
import type { Currency } from '@/api/masterDataApi';
import type { PricingMirrorResult, TotalsMirror } from './usePricingMirror';
import type { UseRowSelectionResult } from './useRowSelection';
import type { DraftFieldValue } from './useQuoteDraft';

/**
 * The shared surface the КП builder grid's presentational children read (волна 3 split).
 *
 * The former monolithic `QuoteBuilderGrid` interleaved ~20 derived closures with the row/rail/
 * toolbar JSX. Rather than drill that through five component layers as props, the facade assembles
 * this one value from its (unchanged) hooks/handlers and provides it; `GridTable`, `GridRow`,
 * `BuilderToolbar` and `EconomicsRail` consume exactly the slices they use. Values and closures are
 * the SAME ones the monolith computed each render — a mechanical move, no behaviour change.
 */
export interface QuoteBuilderGridContextValue {
	// ── Quote-level data ──────────────────────────────────────────────────────────────────────
	activeQuote: Quote;
	econ: QuoteEconomics | null;
	canViewCost: boolean;
	/** Cost columns visible = cost-viewer AND wide enough viewport (narrow drops them to the detail). */
	showCostColumns: boolean;
	presentationCurrency: string;
	vatRate: string;
	effectiveLeadTime: number;
	currencies: Currency[];
	/** Visible main-row column count — drives the detail row + spacer colSpan. */
	mainColCount: number;

	// ── Rows + live pricing ───────────────────────────────────────────────────────────────────
	draftItems: QuoteItem[];
	/**
	 * U4: the rows the TABLE renders — `draftItems` with the in-document filter applied (identical
	 * reference when no filter is active). Only rendering, windowing and keyboard navigation read
	 * this; the pricing mirror, the totals and the save payload keep reading the FULL `draftItems`,
	 * so a filtered view never changes what the КП is worth or what gets saved.
	 */
	visibleItems: QuoteItem[];
	/**
	 * U4: row id → its 0-based index in the FULL document. Rows keep their real КП number (and true
	 * «удалить строку N» / «выбрать строку N» labels) while a filter hides their neighbours.
	 */
	documentIndexById: Map<number, number>;
	/** U4: current «найти в КП» query (raw input value). */
	filterQuery: string;
	setFilterQuery: Dispatch<SetStateAction<string>>;
	/** U4: a filter is narrowing the table right now (query non-empty). */
	isFiltered: boolean;
	pricingMirror: PricingMirrorResult;
	mirrorTotals: TotalsMirror;
	selection: UseRowSelectionResult;

	// ── Per-cell editing + errors ─────────────────────────────────────────────────────────────
	/**
	 * DT1: `null` is a real value here, not "no change" — `margin_percent: null` means «наследовать
	 * маржу КП», distinct from `'0'` («по себестоимости»). See `DraftFieldValue`.
	 */
	handleFieldChange: (id: number, field: keyof QuoteItem, value: DraftFieldValue) => void;
	cellError: (id: number, field: string) => string | undefined;
	cellErrors: Record<string, string>;
	hiddenErrorFields: (errors: Record<string, string>, id: number, showCost: boolean) => string[];
	fieldLabel: (field: string) => string;

	// ── Row expand/collapse (per-line detail sub-row) ─────────────────────────────────────────
	expandedRowId: number | null;
	toggleRow: (id: number) => void;
	setExpandedRowId: Dispatch<SetStateAction<number | null>>;

	// ── Section collapse (U5) — group ITEM/NOTE rows under a SECTION heading, hide when collapsed.
	/** Is this SECTION heading currently collapsed (its children removed from `visibleItems`)? */
	isSectionCollapsed: (sectionId: number) => boolean;
	/** Collapse ↔ expand a SECTION (client-only, persisted to localStorage). */
	toggleSectionCollapse: (sectionId: number) => void;
	/** Row ids of non-SECTION lines that belong to a SECTION — drives the left-indent grouping cue. */
	itemsUnderSection: Set<number>;

	// ── FX + cost display helpers ─────────────────────────────────────────────────────────────
	fxRateFor: (code?: string) => string;
	lineCostInPresentation: (item: QuoteItem) => string;

	// ── Row actions ───────────────────────────────────────────────────────────────────────────
	handleDeleteItem: (id: number) => void;
	setReassignItemId: Dispatch<SetStateAction<number | null>>;
	rowRefs: MutableRefObject<Map<number, HTMLTableRowElement>>;
	// S1: перемещение строки ↑/↓ (swap position) + инлайн-переименование заголовка SECTION / текста NOTE.
	handleMoveRow: (id: number, direction: 'up' | 'down') => void;
	handleRenameRow: (id: number, value: string) => void;
	/**
	 * U1/U4: reordering is suppressed while the table is filtered. ↑/↓ swap POSITIONS with the
	 * adjacent row in the FULL document, which under a filter is a row the seller cannot see — so the
	 * buttons render disabled with an explanatory tooltip instead of silently moving a hidden line.
	 */
	reorderDisabled: boolean;

	// ── Toolbar ───────────────────────────────────────────────────────────────────────────────
	showAddRow: boolean;
	setShowAddRow: Dispatch<SetStateAction<boolean>>;
	// S1: «+ Секция» / «+ Заметка» — добавить строку-заголовок / заметку в конец КП.
	handleAddSection: () => void;
	handleAddNote: () => void;
	openPasteDialog: () => void;
	setShowAiMatch: Dispatch<SetStateAction<boolean>>;
	handlePricingAssist: () => void;
	pricingBusy: boolean;
	fullscreen: boolean;
	setFullscreen: Dispatch<SetStateAction<boolean>>;
	setShowSettings: Dispatch<SetStateAction<boolean>>;

	// ── Economics rail ────────────────────────────────────────────────────────────────────────
	railAsSheet: boolean;
	railOpen: boolean;
	railSheetOpen: boolean;
	setRailSheetOpen: Dispatch<SetStateAction<boolean>>;
	toggleRail: () => void;

	// ── Grid table (scroll container + windowing) ─────────────────────────────────────────────
	scrollContainerRef: RefObject<HTMLDivElement>;
	gridKeyboardOnKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
	handleGridPaste: (event: ClipboardEvent<HTMLDivElement>) => void;
	virtualizer: Virtualizer<HTMLDivElement, Element>;
	/** Windowed rendering is active only above VIRTUALIZE_THRESHOLD rows. */
	shouldVirtualize: boolean;

	// ── Row density (U7) ──────────────────────────────────────────────────────────────────────
	/** Current grid row density — `comfortable` (default) or `compact`. */
	/** Active builder tab — item-level toolbar actions are hidden on the charges tab (they'd act on
	 *  the hidden line list). */
	activeTab: 'items' | 'charges';
	gridDensity: GridDensity;
	/** Flip comfortable ↔ compact (persisted). Drives BOTH the row padding class + estimateSize. */
	toggleGridDensity: () => void;
	/**
	 * Vertical-padding utility class for a body row's padded cells, derived from `gridDensity`
	 * (`py-1.5` comfortable / `py-0.5` compact). Kept in lockstep with the virtualizer estimateSize.
	 */
	rowPaddingY: string;

	// ── Add-row («добавить и продолжить») ─────────────────────────────────────────────────────
	newItemName: string;
	setNewItemName: Dispatch<SetStateAction<string>>;
	newItemQty: string;
	setNewItemQty: Dispatch<SetStateAction<string>>;
	newItemPrice: string;
	setNewItemPrice: Dispatch<SetStateAction<string>>;
	handleAddItem: () => void;
	addNameRef: RefObject<HTMLInputElement>;
	addRowRef: RefObject<HTMLTableRowElement>;
	createItemPending: boolean;
}

const QuoteBuilderGridContext = createContext<QuoteBuilderGridContextValue | null>(null);

export const QuoteBuilderGridProvider = QuoteBuilderGridContext.Provider;

/** Read the grid context; throws if a child is rendered outside the grid facade (developer error). */
export function useQuoteBuilderGrid(): QuoteBuilderGridContextValue {
	const context = useContext(QuoteBuilderGridContext);
	if (context === null) {
		throw new Error('useQuoteBuilderGrid must be used within the QuoteBuilderGrid facade');
	}
	return context;
}
