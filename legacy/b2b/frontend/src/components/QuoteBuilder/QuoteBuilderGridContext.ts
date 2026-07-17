import { createContext, useContext } from 'react';
import type { Dispatch, SetStateAction, RefObject, MutableRefObject, ClipboardEvent, KeyboardEvent } from 'react';
import type { Virtualizer } from '@tanstack/react-virtual';
import type { Quote, QuoteItem, QuoteEconomics } from '@/api/crmApi';
import type { Currency } from '@/api/masterDataApi';
import type { PricingMirrorResult, TotalsMirror } from './usePricingMirror';
import type { UseRowSelectionResult } from './useRowSelection';

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
	pricingMirror: PricingMirrorResult;
	mirrorTotals: TotalsMirror;
	selection: UseRowSelectionResult;

	// ── Per-cell editing + errors ─────────────────────────────────────────────────────────────
	handleFieldChange: (id: number, field: keyof QuoteItem, value: string | number) => void;
	cellError: (id: number, field: string) => string | undefined;
	cellErrors: Record<string, string>;
	hiddenErrorFields: (errors: Record<string, string>, id: number, showCost: boolean) => string[];
	fieldLabel: (field: string) => string;

	// ── Row expand/collapse ───────────────────────────────────────────────────────────────────
	expandedRowId: number | null;
	toggleRow: (id: number) => void;
	setExpandedRowId: Dispatch<SetStateAction<number | null>>;

	// ── FX + cost display helpers ─────────────────────────────────────────────────────────────
	fxRateFor: (code?: string) => string;
	lineCostInPresentation: (item: QuoteItem) => string;

	// ── Row actions ───────────────────────────────────────────────────────────────────────────
	handleDeleteItem: (id: number) => void;
	setReassignItemId: Dispatch<SetStateAction<number | null>>;
	rowRefs: MutableRefObject<Map<number, HTMLTableRowElement>>;

	// ── Toolbar ───────────────────────────────────────────────────────────────────────────────
	showAddRow: boolean;
	setShowAddRow: Dispatch<SetStateAction<boolean>>;
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
