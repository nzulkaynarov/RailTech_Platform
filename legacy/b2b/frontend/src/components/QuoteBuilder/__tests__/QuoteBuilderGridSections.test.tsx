import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';

/**
 * S1 (спека §5 п.19) — sections / notes / optional lines in the КП builder:
 *   • «+ Секция» / «+ Заметка» create a SECTION / NOTE row (create mutation);
 *   • the grid renders all three display_types (ITEM row, SECTION heading, NOTE line);
 *   • ↑/↓ swap `position` via the bulk-update payload;
 *   • the «опция» toggle marks the row and is sent in the save payload;
 *   • Excel-style ArrowDown skips a SECTION row (no navigable cell).
 */

const bulkMutateAsync = vi.fn();
const createMutateAsync = vi.fn();
const updateMutateAsync = vi.fn();

let serverItems: QuoteItem[] = [];
let serverDeal: Deal | undefined;

vi.mock('@/hooks/useCRM', () => ({
	useQuoteItems: () => ({ data: serverItems, isLoading: false }),
	useDeal: () => ({ data: serverDeal, isLoading: false }),
	useUpdateQuoteItem: () => ({ mutateAsync: updateMutateAsync, isPending: false }),
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

// Wide viewport → cost columns render.
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
		quote_currency: 'UZS', cost_currency_default: 'UZS', vat_rate: '12', margin_percent: '0',
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

function makeItem(id: number, overrides: Partial<QuoteItem> = {}): QuoteItem {
	return {
		id, quote: 100, display_type: 'ITEM', is_optional: false, position: id,
		imported_raw_name: `Позиция ${id}`, quantity: 2,
		frozen_base_price: '400', frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '0',
		margin_percent: '0', discount_percent: '0', lead_time_days: 0,
		landed_cost: '400', final_price_excl_vat: '400', version: 1,
		...overrides,
	} as QuoteItem;
}

beforeEach(() => {
	bulkMutateAsync.mockReset().mockResolvedValue([]);
	createMutateAsync.mockReset().mockResolvedValue(makeItem(9));
	updateMutateAsync.mockReset().mockResolvedValue(makeItem(1));
	vi.mocked(toast.success).mockReset();
	vi.mocked(toast.error).mockReset();
	serverItems = [makeItem(1), makeItem(2)];
	serverDeal = { id: 42, active_quote: makeQuote(), created_at: '2026-07-01T00:00:00Z' } as Deal;
});

describe('QuoteBuilderGrid — sections / notes / optional (S1)', () => {
	it('renders all three display_types: ITEM row, SECTION heading, NOTE line', () => {
		serverItems = [
			makeItem(1, { position: 1 }),
			makeItem(2, { display_type: 'SECTION', imported_raw_name: 'Механика', position: 2 }),
			makeItem(3, { display_type: 'NOTE', imported_raw_name: 'сроки уточняются', position: 3 }),
		];
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// ITEM row → a qty cell; SECTION → an editable heading; NOTE → an editable note line.
		expect(screen.getAllByRole('textbox', { name: 'Кол-во' })).toHaveLength(1);
		expect((screen.getByRole('textbox', { name: 'Название раздела' }) as HTMLInputElement).value).toBe('Механика');
		expect((screen.getByRole('textbox', { name: 'Текст заметки' }) as HTMLInputElement).value).toBe('сроки уточняются');
	});

	it('«+ Секция» creates a SECTION row via the create mutation', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: 'Секция' }));
		await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1));
		expect(createMutateAsync.mock.calls[0][0]).toMatchObject({
			quote: 100, display_type: 'SECTION', imported_raw_name: 'Новый раздел',
		});
	});

	it('«+ Заметка» creates a NOTE row via the create mutation', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: 'Заметка' }));
		await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1));
		expect(createMutateAsync.mock.calls[0][0]).toMatchObject({ quote: 100, display_type: 'NOTE' });
	});

	it('↑/↓ swaps position with the neighbour via the bulk-update payload', async () => {
		serverItems = [
			makeItem(1, { position: 1 }),
			makeItem(2, { display_type: 'SECTION', imported_raw_name: 'Механика', position: 2 }),
			makeItem(3, { position: 3 }),
		];
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// The SECTION row (index 1) is neither first nor last → move it down, swapping with item #3.
		await user.click(screen.getByRole('button', { name: 'Переместить вниз' }));
		await waitFor(() => expect(bulkMutateAsync).toHaveBeenCalledTimes(1));

		const payload = bulkMutateAsync.mock.calls[0][0];
		expect(payload.quoteId).toBe(100);
		// Section (was pos 2) takes 3; item #3 (was pos 3) takes 2 — a clean swap.
		expect(payload.items).toEqual(
			expect.arrayContaining([
				expect.objectContaining({ id: 2, position: 3 }),
				expect.objectContaining({ id: 3, position: 2 }),
			]),
		);
	});

	it('the «опция» toggle marks the row dirty and the save payload carries is_optional', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Toggle optional on the SECOND item.
		const optionalToggles = screen.getAllByRole('checkbox', { name: /Опциональная позиция/ });
		expect(optionalToggles).toHaveLength(2);
		await user.click(optionalToggles[1]);

		// «опц.» badge appears + unsaved-changes indicator.
		await waitFor(() => expect(screen.getByText('опц.')).toBeInTheDocument());
		expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();

		// Save → the bulk-update carries is_optional=true for the toggled row.
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));
		await waitFor(() => expect(bulkMutateAsync).toHaveBeenCalledTimes(1));
		const savePayload = bulkMutateAsync.mock.calls[0][0];
		expect(savePayload.items).toEqual([
			expect.objectContaining({ id: 2, is_optional: true }),
		]);
	});

	it('ArrowDown skips a SECTION row and lands on the next ITEM cell', async () => {
		serverItems = [
			makeItem(1, { position: 1 }),
			makeItem(2, { display_type: 'SECTION', imported_raw_name: 'Механика', position: 2 }),
			makeItem(3, { position: 3 }),
		];
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Only the two ITEM rows expose a qty cell; the SECTION row has none.
		const qtyCells = screen.getAllByRole('textbox', { name: 'Кол-во' });
		expect(qtyCells).toHaveLength(2);
		await user.click(qtyCells[0]);
		await user.keyboard('{ArrowDown}');

		// Focus jumped straight to the next ITEM row's qty cell — the SECTION between was skipped.
		expect(document.activeElement).toBe(qtyCells[1]);
	});
});
