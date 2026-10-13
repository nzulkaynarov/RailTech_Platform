import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';

/**
 * WP-J / spec §5 волна 2 п.11 — the КП grid's bulk actions + row error marker.
 *   • selecting rows + «Дублировать» calls bulk-create with the copied payload;
 *   • a bulk-save rejection on a field that lives in the COLLAPSED detail sub-row
 *     surfaces a row-level error marker and auto-expands the detail; collapsing then
 *     clicking the marker re-expands it.
 */

const bulkUpdateMutateAsync = vi.fn();
const bulkCreateMutateAsync = vi.fn();
const bulkDeleteMutateAsync = vi.fn();

let serverItems: QuoteItem[] = [];
let serverDeal: Deal | undefined;

vi.mock('@/hooks/useCRM', () => ({
	useQuoteItems: () => ({ data: serverItems, isLoading: false }),
	useDeal: () => ({ data: serverDeal, isLoading: false }),
	useUpdateQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useBulkUpdateQuoteItems: () => ({ mutateAsync: bulkUpdateMutateAsync, isPending: false }),
	useBulkCreateQuoteItems: () => ({ mutateAsync: bulkCreateMutateAsync, isPending: false }),
	useBulkDeleteQuoteItems: () => ({ mutateAsync: bulkDeleteMutateAsync, isPending: false }),
	useCreateQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useDeleteQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useSetQuoteDeliveryBasis: () => ({ mutate: vi.fn(), isPending: false }),
	useReassignProduct: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/hooks/useMasterData', () => ({
	useCurrencies: () => ({ data: [{ id: 1, code: 'UZS' }, { id: 2, code: 'USD' }] }),
}));

// Wide viewport → cost columns render (so the detail-only fields are the hidden ones).
vi.mock('@/hooks/use-mobile', () => ({ useMediaQuery: () => false }));

vi.mock('@/components/QuoteBuilder/AICatalogMatchDialog', () => ({ AICatalogMatchDialog: () => null }));
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
import { QuoteBuilderGrid } from '@/components/QuoteBuilder/QuoteBuilderGrid';

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

function makeItem(id: number, name: string, quantity: number, price: string): QuoteItem {
	return {
		id, quote: 100, imported_raw_name: name, quantity,
		frozen_base_price: price, frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '0',
		margin_percent: '0', discount_percent: '0', lead_time_days: 0,
		landed_cost: price, final_price_excl_vat: price,
	} as QuoteItem;
}

beforeEach(() => {
	bulkUpdateMutateAsync.mockReset();
	bulkCreateMutateAsync.mockReset();
	bulkDeleteMutateAsync.mockReset();
	vi.mocked(toast.success).mockReset();
	vi.mocked(toast.error).mockReset();
	serverItems = [makeItem(1, 'Болт М12', 4, '1500'), makeItem(2, 'Гайка М12', 8, '300')];
	serverDeal = { id: 42, active_quote: makeQuote(), created_at: '2026-07-01T00:00:00Z' } as Deal;
});

describe('QuoteBuilderGrid — bulk duplicate', () => {
	it('selecting a row and «Дублировать» calls bulk-create with the copied payload', async () => {
		bulkCreateMutateAsync.mockResolvedValue([]);
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('checkbox', { name: 'Выбрать позицию 1' }));
		// The selection strip appears with the count.
		expect(screen.getByText('Выбрано: 1')).toBeInTheDocument();

		await user.click(screen.getByRole('button', { name: 'Дублировать' }));

		await waitFor(() => expect(bulkCreateMutateAsync).toHaveBeenCalledTimes(1));
		const arg = bulkCreateMutateAsync.mock.calls[0][0];
		expect(arg.quoteId).toBe(100);
		expect(arg.items).toHaveLength(1);
		expect(arg.items[0].imported_raw_name).toBe('Болт М12 (копия)');
		expect(arg.items[0].quantity).toBe(4);
		expect(arg.items[0].frozen_base_price).toBe('1500');
	});

	it('header checkbox selects all rows → duplicate copies every selected line', async () => {
		bulkCreateMutateAsync.mockResolvedValue([]);
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('checkbox', { name: 'Выбрать все позиции' }));
		expect(screen.getByText('Выбрано: 2')).toBeInTheDocument();

		await user.click(screen.getByRole('button', { name: 'Дублировать' }));
		await waitFor(() => expect(bulkCreateMutateAsync).toHaveBeenCalledTimes(1));
		expect(bulkCreateMutateAsync.mock.calls[0][0].items).toHaveLength(2);
	});
});

describe('QuoteBuilderGrid — row error marker for a hidden field', () => {
	it('shows the marker + auto-expands the detail on a customs_duty rejection, and the marker re-expands after collapse', async () => {
		bulkUpdateMutateAsync.mockRejectedValue({
			response: {
				data: {
					detail: 'QUOTE_ITEMS_BULK_INVALID',
					rows: [{ id: 1, index: 0, errors: { customs_duty: ['QUOTE_ITEM_PRICE_INVALID'] } }],
				},
			},
		});
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Make row 1 dirty (edit the visible qty), then save → the batch is rejected.
		const qty = screen.getAllByRole('textbox', { name: 'Кол-во' })[0];
		await user.click(qty);
		await user.clear(qty);
		await user.type(qty, '5');
		await user.tab();
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));

		await waitFor(() => expect(bulkUpdateMutateAsync).toHaveBeenCalledTimes(1));

		// The row marker (error on the collapsed customs_duty field) is shown…
		const marker = await screen.findByRole('button', { name: 'Ошибки в свёрнутых полях' });
		expect(marker).toBeInTheDocument();
		// …and the detail auto-expanded, so the customs_duty cell is on screen and invalid.
		const customsCell = await screen.findByRole('textbox', { name: 'Тамож. платёж, за ед.' });
		expect(customsCell).toHaveAttribute('aria-invalid', 'true');

		// Collapse the row via the chevron → the detail (and its customs cell) disappears.
		await user.click(screen.getAllByRole('button', { name: 'Детализация позиции' })[0]);
		await waitFor(() =>
			expect(screen.queryByRole('textbox', { name: 'Тамож. платёж, за ед.' })).not.toBeInTheDocument(),
		);

		// Clicking the marker re-expands the detail.
		await user.click(screen.getByRole('button', { name: 'Ошибки в свёрнутых полях' }));
		expect(await screen.findByRole('textbox', { name: 'Тамож. платёж, за ед.' })).toBeInTheDocument();
	});
});
