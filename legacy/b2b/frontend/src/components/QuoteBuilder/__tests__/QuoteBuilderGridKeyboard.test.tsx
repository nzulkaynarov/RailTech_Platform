import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';

/**
 * WP-G / spec §5 волна 2 п.10 — Excel-style keyboard navigation over the КП grid cells.
 *   • ArrowDown from a qty cell commits the current row and moves focus one row down;
 *   • Enter in a price cell commits and moves focus down (NumericCell blur + grid step);
 *   • ArrowDown in the last row is a no-op (focus stays put);
 *   • Escape reverts the cell but KEEPS focus (never dumps to <body>);
 *   • the add-row's Enter still adds a line (navigation must not hijack it).
 */

const bulkMutateAsync = vi.fn();
const createMutateAsync = vi.fn();

let serverItems: QuoteItem[] = [];
let serverDeal: Deal | undefined;

vi.mock('@/hooks/useCRM', () => ({
	useQuoteItems: () => ({ data: serverItems, isLoading: false }),
	useDeal: () => ({ data: serverDeal, isLoading: false }),
	useUpdateQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useBulkUpdateQuoteItems: () => ({ mutateAsync: bulkMutateAsync, isPending: false }),
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

// Wide viewport → cost columns (incl. the price cell) render, so both navigable columns exist.
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

beforeEach(() => {
	bulkMutateAsync.mockReset();
	createMutateAsync.mockReset();
	vi.mocked(toast.success).mockReset();
	vi.mocked(toast.error).mockReset();
	// Two rows so navigation has a target above/below.
	serverItems = [makeItem(1, 2, '400'), makeItem(2, 3, '600')];
	serverDeal = { id: 42, active_quote: makeQuote(), created_at: '2026-07-01T00:00:00Z' } as Deal;
});

const DIRTY_LABEL = 'Есть несохранённые изменения';

describe('QuoteBuilderGrid — keyboard navigation', () => {
	it('ArrowDown from a qty cell commits the current row and focuses the qty cell below', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const [qty1, qty2] = screen.getAllByRole('textbox', { name: 'Кол-во' });
		await user.click(qty1);
		await user.clear(qty1);
		await user.type(qty1, '7');
		await user.keyboard('{ArrowDown}');

		// Focus moved down…
		expect(document.activeElement).toBe(qty2);
		// …and the edit on row 1 was committed on the blur (grouped small number «7»).
		expect((qty1 as HTMLInputElement).value).toBe('7');
		await waitFor(() => expect(screen.getByText(DIRTY_LABEL)).toBeInTheDocument());
	});

	it('Enter in a price cell commits and moves focus one row down', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const [price1, price2] = screen.getAllByRole('textbox', { name: /Базовая цена/ });
		await user.click(price1);
		await user.clear(price1);
		await user.type(price1, '555');
		await user.keyboard('{Enter}');

		expect(document.activeElement).toBe(price2);
		expect((price1 as HTMLInputElement).value).toBe('555');
		await waitFor(() => expect(screen.getByText(DIRTY_LABEL)).toBeInTheDocument());
	});

	it('ArrowDown in the last row is a no-op (focus stays put)', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const qtyCells = screen.getAllByRole('textbox', { name: 'Кол-во' });
		const lastQty = qtyCells[qtyCells.length - 1];
		await user.click(lastQty);
		await user.keyboard('{ArrowDown}');

		expect(document.activeElement).toBe(lastQty);
	});

	it('Enter in the last row commits but keeps focus in the cell (no jump to body)', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const priceCells = screen.getAllByRole('textbox', { name: /Базовая цена/ });
		const lastPrice = priceCells[priceCells.length - 1];
		await user.click(lastPrice);
		await user.clear(lastPrice);
		await user.type(lastPrice, '777');
		await user.keyboard('{Enter}');

		// Focus stayed in the source cell (refocused after commit), NOT dumped to <body>.
		expect(document.activeElement).toBe(lastPrice);
		// …and the edit still committed on the Enter blur.
		expect((lastPrice as HTMLInputElement).value).toBe('777');
		await waitFor(() => expect(screen.getByText(DIRTY_LABEL)).toBeInTheDocument());
	});

	it('Escape reverts the cell but keeps focus in it (no jump to body)', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const [qty1] = screen.getAllByRole('textbox', { name: 'Кол-во' });
		await user.click(qty1);
		await user.clear(qty1);
		await user.type(qty1, '99');
		await user.keyboard('{Escape}');

		// Focus stayed in the cell and the value reverted to the server value «3»→«2» (row 1 = 2).
		expect(document.activeElement).toBe(qty1);
		expect((qty1 as HTMLInputElement).value).toBe('2');
		// Nothing committed → no unsaved-changes indicator.
		expect(screen.queryByText(DIRTY_LABEL)).not.toBeInTheDocument();
	});

	it('regression: Enter in the add-row still adds a line (navigation does not hijack it)', async () => {
		createMutateAsync.mockResolvedValue(makeItem(3, 1, '0'));
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: 'Добавить' }));
		await user.type(screen.getByRole('textbox', { name: 'Наименование' }), 'Гайка М12');
		await user.keyboard('{Enter}');

		await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1));
		expect(createMutateAsync.mock.calls[0][0]).toMatchObject({
			quote: 100, imported_raw_name: 'Гайка М12', quantity: 1,
		});
	});
});
