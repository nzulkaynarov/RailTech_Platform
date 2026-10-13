/**
 * Shared constants + pure formatting helpers for the КП builder grid package.
 *
 * Extracted verbatim from the former monolithic `QuoteBuilderGrid.tsx` during the
 * package split (волна 3). Values are unchanged — this is a mechanical move so the
 * grid, its sub-components and its tests keep the exact same behaviour.
 */

// E2: sanity upper caps on line quantity/price — mirror backend settings.QUOTE_ITEM_MAX_*
// (санитарный потолок против fat-finger/вставки; backend re-validates and is the hard guard).
export const QUOTE_ITEM_MAX_QUANTITY = 1000000;
export const QUOTE_ITEM_MAX_UNIT_PRICE = 10000000000;

// DT1 — per-line margin override cap. Mirrors the backend field validators on
// `QuoteItem.margin_percent` (MinValueValidator(0) / MaxValueValidator(500), max_digits=5,
// decimal_places=2 ⇒ 0–500 %). The backend re-validates and is the hard guard; this is the
// KP-04-style input cap so a fat-finger clamps in the cell instead of round-tripping a 400.
export const QUOTE_ITEM_MAX_MARGIN_PERCENT = 500;

// Max lines one Excel-paste batch may create — mirrors backend settings.QUOTE_ITEMS_BULK_MAX_ROWS.
// The client truncates the preview to this cap; the server is the hard guard (QUOTE_ITEMS_BULK_TOO_LARGE).
export const QUOTE_ITEMS_BULK_MAX_ROWS = 500;

// Row count above which the line table switches to windowed (virtualized) rendering (волна 3).
// At or below the threshold every row renders normally, so small КП — and the tests that build
// them — are byte-identical to the pre-virtualization grid.
export const VIRTUALIZE_THRESHOLD = 50;

// U7 — grid row density. `comfortable` is the default, roomy spacing; `compact` trims the vertical
// row padding so more КП lines fit on screen at once. Text size is NEVER reduced below `text-xs`
// (project rule) — only the vertical padding shrinks.
export type GridDensity = 'comfortable' | 'compact';
export const GRID_DENSITY_DEFAULT: GridDensity = 'comfortable';
export const GRID_DENSITIES: readonly GridDensity[] = ['comfortable', 'compact'];

// SINGLE SOURCE OF TRUTH for row height, per density. The estimate the virtualizer seeds
// not-yet-measured rows with MUST track the padding class below — otherwise the window reserves the
// wrong height for off-screen rows and the scrollbar jumps as they measure in. `compact` trims the
// padding class from `py-1.5` (6px) to `py-0.5` (2px) → 8px less per row around the h-8 (32px) cell.
export const GRID_DENSITY_ROW_HEIGHT: Record<GridDensity, number> = {
	comfortable: 44,
	compact: 36,
};

// Vertical-padding utility class applied to a body row's padded cells, per density. Kept in lockstep
// with GRID_DENSITY_ROW_HEIGHT above (the useGridDensity test asserts they move together).
export const GRID_DENSITY_ROW_PADDING: Record<GridDensity, string> = {
	comfortable: 'py-1.5',
	compact: 'py-0.5',
};

// Margin health → semantic color, shared by the КП-level rail and the per-line chip.
export const marginToneClass = (belowCostOrFloor: boolean, marginPct: number, target: number): string =>
	belowCostOrFloor ? 'text-destructive' : marginPct >= target ? 'text-success' : 'text-warning';

// Compact, locale-aware money for the collapsed rail strip (e.g. «7,8 млн»). Locale follows
// the active i18n language (not hardcoded). Full value is always in the tooltip via formatMoney.
export const compactNumber = (value: string | number | null | undefined, locale: string): string =>
	new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value || 0));

// «Добавить и продолжить»: normalize a raw add-row number. Strips grouping whitespace — the plain
// space plus no-break (U+00A0) / narrow no-break (U+202F) that Intl grouping emits — and maps the
// decimal comma to a dot. Add-row inputs are PLAIN controlled inputs, so this runs at submit.
export const parseAddRowNumber = (raw: string): number =>
	Number(String(raw).replace(/\s+/g, '').replace(',', '.'));
