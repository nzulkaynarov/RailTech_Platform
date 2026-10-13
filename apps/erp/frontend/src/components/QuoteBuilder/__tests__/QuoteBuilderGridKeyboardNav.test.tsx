import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act } from 'react';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';
import { parseClipboardTable, toBulkCreateRows } from '@/components/QuoteBuilder/parseClipboardTable';

/**
 * U6 — full keyboard navigation over the КП grid (extends the WP-G ↑/↓ suite):
 *   • ArrowRight/ArrowLeft move between COLUMNS of a row once the caret is at the text edge;
 *   • Tab / Shift+Tab move between CELLS, wrapping to the adjacent row at a row edge;
 *   • Ctrl+C copies the selected rows as TSV that round-trips back through the Excel-paste parser.
 */

const createMutateAsync = vi.fn();
let serverItems: QuoteItem[] = [];
let serverDeal: Deal | undefined;

vi.mock('@/hooks/useCRM', () => ({
	useQuoteItems: () => ({ data: serverItems, isLoading: false }),
	useDeal: () => ({ data: serverDeal, isLoading: false }),
	useUpdateQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useBulkUpdateQuoteItems: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useBulkCreateQuoteItems: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useBulkDeleteQuoteItems: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useCreateQuoteItem: () => ({ mutateAsync: createMutateAsync, isPending: false }),
	useDeleteQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useSetQuoteDeliveryBasis: () => ({ mutate: vi.fn(), isPending: false }),
	useReassignProduct: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/hooks/useMasterData', () => ({
	useCurrencies: () => ({ data: [{ id: 1, code: 'UZS' }, { id: 2, code: 'USD' }] }),
}));

// Wide viewport → all four navigable columns (name · qty · price · margin) render.
vi.mock('@/hooks/use-mobile', () => ({ useMediaQuery: () => false }));

vi.mock('@/components/Admin/AICatalogMatchDialog', () => ({ AICatalogMatchDialog: () => null }));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));
vi.mock('@/components/CRM/QuoteSettingsDialog', () => ({ QuoteSettingsDialog: () => null }));
vi.mock('@/components/CRM/ReassignProductDialog', () => ({ ReassignProductDialog: () => null }));
vi.mock('@/components/CRM/DeliveryBasisSelect', () => ({ DeliveryBasisSelect: () => null }));
vi.mock('@/components/CRM/QuoteChargesSection', () => ({ QuoteChargesSection: () => null }));
vi.mock('@/components/Shared/DocumentActions', () => ({ DocumentActions: () => null }));

vi.mock('sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

// Import AFTER the mocks are registered.
import { QuoteBuilderGrid } from '@/components/Admin/QuoteBuilderGrid';

function makeQuote(): Quote {
	return {
		id: 100, deal: 42, version: 1, status: 1, status_code: 'DRAFT', status_name: 'Черновик',
		quote_currency: 'UZS', cost_currency_default: 'UZS', vat_rate: '12', margin_percent: '20',
		fx_snapshot: {}, fx_manual: {}, items: [], charges: [],
		subtotal_excl_vat: '1000', charges_total: '0', vat_amount: '120', total_incl_vat: '1120',
		frozen_at: null,
		economics: {
			total_landed_cost: '800', gross_profit: '200', gross_margin_percent: '20',
			markup_percent: '25', charge_cost_total: '0', operating_profit: '200',
			below_cost: false, below_floor: false, min_margin_percent: '15',
			target_margin_percent: '25', fx_missing: [],
		},
		created_at: '2026-07-01T00:00:00Z',
	} as Quote;
}

function makeItem(id: number, quantity: number, price: string): QuoteItem {
	return {
		id, quote: 100, imported_raw_name: `Позиция ${id}`, quantity,
		frozen_base_price: price, frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '0',
		margin_percent: '0', discount_percent: '0', lead_time_days: 0,
		landed_cost: price, final_price_excl_vat: price,
	} as QuoteItem;
}

/** The <input> for a given row id + column, matched by the grid's data attributes. */
const cellOf = (rowId: number, column: string): HTMLInputElement =>
	document.querySelector(`[data-cell-row="${rowId}"][data-cell-col="${column}"]`) as HTMLInputElement;

/** Focus an input and pin the collapsed caret at start/end so the ←/→ edge gate is deterministic. */
function focusAtCaret(input: HTMLInputElement, position: 'start' | 'end') {
	act(() => input.focus());
	const offset = position === 'end' ? input.value.length : 0;
	input.setSelectionRange(offset, offset);
}

beforeEach(() => {
	createMutateAsync.mockReset();
	vi.mocked(toast.success).mockReset();
	vi.mocked(toast.error).mockReset();
	serverItems = [makeItem(1, 2, '400'), makeItem(2, 3, '600')];
	serverDeal = { id: 42, active_quote: makeQuote(), created_at: '2026-07-01T00:00:00Z' } as Deal;
});

describe('QuoteBuilderGrid — U6 keyboard navigation', () => {
	it('ArrowRight at the caret end moves to the next column of the same row', () => {
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		const qty1 = cellOf(1, 'quantity');
		const price1 = cellOf(1, 'frozen_base_price');

		focusAtCaret(qty1, 'end');
		fireEvent.keyDown(qty1, { key: 'ArrowRight' });

		expect(document.activeElement).toBe(price1);
	});

	it('ArrowLeft at the caret start moves to the previous column of the same row', () => {
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		const qty1 = cellOf(1, 'quantity');
		const price1 = cellOf(1, 'frozen_base_price');

		focusAtCaret(price1, 'start');
		fireEvent.keyDown(price1, { key: 'ArrowLeft' });

		expect(document.activeElement).toBe(qty1);
	});

	it('ArrowRight does NOT jump columns while the caret still has room in the cell', () => {
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		const qty1 = cellOf(1, 'quantity');

		// Caret at the START of a non-empty value → the browser owns the key, focus must stay put.
		focusAtCaret(qty1, 'start');
		fireEvent.keyDown(qty1, { key: 'ArrowRight' });

		expect(document.activeElement).toBe(qty1);
	});

	it('Tab moves to the next cell in the same row', () => {
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		const qty1 = cellOf(1, 'quantity');
		const price1 = cellOf(1, 'frozen_base_price');

		act(() => qty1.focus());
		fireEvent.keyDown(qty1, { key: 'Tab' });

		expect(document.activeElement).toBe(price1);
	});

	it('Tab from the last cell of a row wraps to the first cell of the next row', () => {
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		const margin1 = cellOf(1, 'margin_percent');
		const name2 = cellOf(2, 'name');

		act(() => margin1.focus());
		fireEvent.keyDown(margin1, { key: 'Tab' });

		expect(document.activeElement).toBe(name2);
	});

	it('Shift+Tab from the first cell of a row wraps to the last cell of the previous row', () => {
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		const name2 = cellOf(2, 'name');
		const margin1 = cellOf(1, 'margin_percent');

		act(() => name2.focus());
		fireEvent.keyDown(name2, { key: 'Tab', shiftKey: true });

		expect(document.activeElement).toBe(margin1);
	});

	it('Ctrl+C on the selected rows writes TSV that round-trips through the Excel-paste parser', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Select both rows via the header «выбрать все» checkbox, then copy.
		const selectAll = screen.getByRole('checkbox', { name: 'Выбрать все позиции' });
		await user.click(selectAll);
		// Install the spy AFTER userEvent.setup() (which stubs navigator.clipboard itself).
		const writeText = vi.fn().mockResolvedValue(undefined);
		Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText, readText: vi.fn() } });
		fireEvent.keyDown(selectAll, { key: 'c', ctrlKey: true });

		await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
		const tsv = writeText.mock.calls[0][0] as string;
		const parsed = parseClipboardTable(tsv);
		const rows = toBulkCreateRows(parsed, parsed.roles, 100);
		expect(rows).toEqual([
			{ imported_raw_name: 'Позиция 1', quantity: 2, frozen_base_price: '400' },
			{ imported_raw_name: 'Позиция 2', quantity: 3, frozen_base_price: '600' },
		]);
	});

	it('Ctrl+C with no rows selected does not hijack the native copy', () => {
		const writeText = vi.fn().mockResolvedValue(undefined);
		Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText, readText: vi.fn() } });
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const qty1 = cellOf(1, 'quantity');
		act(() => qty1.focus());
		fireEvent.keyDown(qty1, { key: 'c', ctrlKey: true });

		expect(writeText).not.toHaveBeenCalled();
	});
});
