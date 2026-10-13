import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';

import { renderWithProviders, createTestQueryClient } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';

/**
 * Optimistic locking on QuoteItem (spec §5.3, волна 3). A bulk save that lost a race to a
 * colleague comes back with a per-row QUOTE_ITEM_STALE code inside the QUOTE_ITEMS_BULK_INVALID
 * envelope. Unlike a validation error, the grid must NOT highlight cells — it opens a refresh
 * dialog, and «Обновить» refetches ['quote-items] so the fresh server values replace the stale
 * edits. The happy path (no conflict) must still save and echo the row version in the payload.
 */

const bulkMutateAsync = vi.fn();

let serverItems: QuoteItem[] = [];
let serverDeal: Deal | undefined;

vi.mock('@/hooks/useCRM', () => ({
	useQuoteItems: () => ({ data: serverItems, isLoading: false }),
	useDeal: () => ({ data: serverDeal, isLoading: false }),
	useUpdateQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useBulkUpdateQuoteItems: () => ({ mutateAsync: bulkMutateAsync, isPending: false }),
	useBulkCreateQuoteItems: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useBulkDeleteQuoteItems: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useCreateQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useDeleteQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useSetQuoteDeliveryBasis: () => ({ mutate: vi.fn(), isPending: false }),
	useReassignProduct: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/hooks/useMasterData', () => ({
	useCurrencies: () => ({ data: [{ id: 1, code: 'UZS' }, { id: 2, code: 'USD' }] }),
}));

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

function makeItem(id: number): QuoteItem {
	return {
		id, quote: 100, imported_raw_name: 'Болт', quantity: 2, version: 3,
		frozen_base_price: '400', frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '0',
		margin_percent: '0', discount_percent: '0', lead_time_days: 0,
		landed_cost: '400', final_price_excl_vat: '500',
	} as QuoteItem;
}

beforeEach(() => {
	bulkMutateAsync.mockReset();
	vi.mocked(toast.success).mockReset();
	vi.mocked(toast.error).mockReset();
	vi.mocked(toast.info).mockReset();
	serverItems = [makeItem(1)];
	serverDeal = { id: 42, active_quote: makeQuote(), created_at: '2026-07-01T00:00:00Z' } as Deal;
});

async function editQuantityTo(value: string) {
	const user = userEvent.setup();
	const qty = screen.getByRole('textbox', { name: 'Кол-во' });
	await user.click(qty);
	await user.clear(qty);
	await user.type(qty, value);
	await user.tab(); // blur → commit → row is now dirty
	return user;
}

describe('QuoteBuilderGrid — optimistic-lock conflict (волна 3)', () => {
	it('echoes the row version in the bulk payload and saves on the happy path', async () => {
		bulkMutateAsync.mockResolvedValue([makeItem(1)]);
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const user = await editQuantityTo('5');
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));

		await waitFor(() => expect(bulkMutateAsync).toHaveBeenCalledTimes(1));
		// The row's last-read version travels with the edit so the server can detect a stale write.
		expect(bulkMutateAsync.mock.calls[0][0].items[0]).toMatchObject({ id: 1, quantity: '5', version: 3 });
		await waitFor(() => expect(toast.success).toHaveBeenCalled());
		// No conflict dialog on a clean save.
		expect(screen.queryByText('Строки изменены другим пользователем')).not.toBeInTheDocument();
	});

	it('opens the conflict dialog (not a cell highlight) on a QUOTE_ITEM_STALE row and refetches on «Обновить»', async () => {
		bulkMutateAsync.mockRejectedValue({
			response: {
				data: {
					detail: 'QUOTE_ITEMS_BULK_INVALID',
					rows: [{ id: 1, index: 0, errors: { version: ['QUOTE_ITEM_STALE'] } }],
				},
			},
		});
		const queryClient = createTestQueryClient();
		const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
		renderWithProviders(<QuoteBuilderGrid dealId={42} />, { queryClient });

		const user = await editQuantityTo('5');
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));

		await waitFor(() => expect(bulkMutateAsync).toHaveBeenCalledTimes(1));
		// The conflict dialog is shown — the seller's edit is a concurrency loss, not a bad input.
		await waitFor(() => expect(screen.getByText('Строки изменены другим пользователем')).toBeInTheDocument());
		// This is NOT the validation-error path: no per-cell «rows with errors» toast fires.
		expect(toast.error).not.toHaveBeenCalled();
		// Nothing was saved → the unsaved-changes state is preserved until the seller refreshes.
		expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();

		invalidateSpy.mockClear();
		await user.click(screen.getByRole('button', { name: 'Обновить' }));

		// «Обновить» refetches the quote-items so the fresh server values re-merge.
		await waitFor(() =>
			expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['quote-items'] }),
		);
		expect(toast.info).toHaveBeenCalled();
		// The dialog closes after refresh.
		await waitFor(() =>
			expect(screen.queryByText('Строки изменены другим пользователем')).not.toBeInTheDocument(),
		);
	});
});
