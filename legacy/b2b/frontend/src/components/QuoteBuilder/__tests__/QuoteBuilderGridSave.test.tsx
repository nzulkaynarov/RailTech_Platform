import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';

/**
 * WP-F / spec §2 P0-4 — the КП builder grid's transactional bulk save.
 *   • success → the bulk mutation fires ONCE and the unsaved-changes state clears;
 *   • QUOTE_ITEMS_BULK_INVALID → the offending cell is aria-invalid and the dirty
 *     state is PRESERVED (the transaction wrote nothing);
 *   • the add-row is «add & continue» — it stays open and clears after each add.
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
	useCreateQuoteItem: () => ({ mutateAsync: createMutateAsync, isPending: false }),
	useDeleteQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useSetQuoteDeliveryBasis: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('@/hooks/useMasterData', () => ({
	useCurrencies: () => ({ data: [{ id: 1, code: 'UZS' }, { id: 2, code: 'USD' }] }),
}));

vi.mock('@/hooks/use-mobile', () => ({ useMediaQuery: () => false }));

// Heavy child surfaces aren't under test here — stub to null so the grid renders in isolation.
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
	};
}

function makeItem(id: number): QuoteItem {
	return {
		id, quote: 100, imported_raw_name: 'Болт', quantity: 2,
		frozen_base_price: '400', frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '0',
		margin_percent: '0', discount_percent: '0', lead_time_days: 0,
		landed_cost: '400', final_price_excl_vat: '500',
	} as QuoteItem;
}

beforeEach(() => {
	bulkMutateAsync.mockReset();
	createMutateAsync.mockReset();
	vi.mocked(toast.success).mockReset();
	vi.mocked(toast.error).mockReset();
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

describe('QuoteBuilderGrid — transactional bulk save', () => {
	it('saves all dirty rows in ONE bulk call and clears the unsaved state on success', async () => {
		bulkMutateAsync.mockResolvedValue([makeItem(1)]);
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const user = await editQuantityTo('5');
		expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();

		await user.click(screen.getByRole('button', { name: 'Сохранить' }));

		await waitFor(() => expect(bulkMutateAsync).toHaveBeenCalledTimes(1));
		const arg = bulkMutateAsync.mock.calls[0][0];
		expect(arg.quoteId).toBe(100);
		expect(arg.items).toHaveLength(1);
		expect(arg.items[0]).toMatchObject({ id: 1, quantity: '5' });
		await waitFor(() => expect(toast.success).toHaveBeenCalled());
		// Dirty state cleared → the unsaved indicator is gone.
		expect(screen.queryByText('Есть несохранённые изменения')).not.toBeInTheDocument();
	});

	it('marks the offending cell aria-invalid and KEEPS the dirty state on QUOTE_ITEMS_BULK_INVALID', async () => {
		bulkMutateAsync.mockRejectedValue({
			response: {
				data: {
					detail: 'QUOTE_ITEMS_BULK_INVALID',
					rows: [{ id: 1, index: 0, errors: { quantity: ['QUOTE_ITEM_QTY_INVALID'] } }],
				},
			},
		});
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const user = await editQuantityTo('5');
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));

		await waitFor(() => expect(bulkMutateAsync).toHaveBeenCalledTimes(1));
		const qty = screen.getByRole('textbox', { name: 'Кол-во' });
		await waitFor(() => expect(qty).toHaveAttribute('aria-invalid', 'true'));
		// The localized code message rides on the cell as its tooltip.
		expect(qty).toHaveAttribute('title', 'Количество должно быть не меньше 1');
		// Transaction wrote nothing → the dirty state (and its indicator) survives.
		expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();
		expect(toast.error).toHaveBeenCalled();
	});

	it('re-editing a rejected cell clears its invalid state', async () => {
		bulkMutateAsync.mockRejectedValue({
			response: {
				data: {
					detail: 'QUOTE_ITEMS_BULK_INVALID',
					rows: [{ id: 1, index: 0, errors: { quantity: ['QUOTE_ITEM_QTY_INVALID'] } }],
				},
			},
		});
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const user = await editQuantityTo('5');
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));
		const qty = screen.getByRole('textbox', { name: 'Кол-во' });
		await waitFor(() => expect(qty).toHaveAttribute('aria-invalid', 'true'));

		await user.click(qty);
		await user.clear(qty);
		await user.type(qty, '3');
		await user.tab();
		expect(qty).not.toHaveAttribute('aria-invalid', 'true');
	});
});

describe('QuoteBuilderGrid — «add & continue» row', () => {
	it('adds a line, keeps the add-row open and clears the name for the next entry', async () => {
		createMutateAsync.mockResolvedValue(makeItem(2));
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Open the add-row from the toolbar.
		await user.click(screen.getByRole('button', { name: 'Добавить' }));
		const nameInput = screen.getByRole('textbox', { name: 'Наименование' });
		await user.type(nameInput, 'Гайка М10');
		await user.keyboard('{Enter}'); // «добавить и продолжить»

		await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1));
		expect(createMutateAsync.mock.calls[0][0]).toMatchObject({
			quote: 100, imported_raw_name: 'Гайка М10', quantity: 1,
		});
		// The add-row stays open and the name is cleared for the next line.
		await waitFor(() => {
			expect(screen.getByRole('textbox', { name: 'Наименование' })).toHaveValue('');
		});
	});

	it('submits the just-typed qty and price on Enter (no stale-closure loss)', async () => {
		// Adversarial-review MAJOR: NumericCell committed on blur, so Enter-submit read
		// stale qty/price and the line was created with defaults 1 / 0. The add-row now
		// uses plain controlled inputs; Enter must carry exactly what was typed.
		createMutateAsync.mockResolvedValue(makeItem(2));
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: 'Добавить' }));
		await user.type(screen.getByRole('textbox', { name: 'Наименование' }), 'Автосцепка СА-3');
		// The grid row renders its own qty/price cells — the add-row inputs are the LAST ones.
		const qtyInputs = screen.getAllByRole('textbox', { name: 'Кол-во' });
		const qtyInput = qtyInputs[qtyInputs.length - 1];
		await user.clear(qtyInput);
		await user.type(qtyInput, '50');
		const priceInputs = screen.getAllByRole('textbox', { name: /Базовая цена/ });
		const priceInput = priceInputs[priceInputs.length - 1];
		await user.clear(priceInput);
		await user.type(priceInput, '777,50');
		await user.keyboard('{Enter}'); // Enter прямо в поле цены — без blur

		await waitFor(() => expect(createMutateAsync).toHaveBeenCalledTimes(1));
		expect(createMutateAsync.mock.calls[0][0]).toMatchObject({
			quote: 100, imported_raw_name: 'Автосцепка СА-3', quantity: 50, frozen_base_price: '777.5',
		});
	});

	it('closes the add-row on Escape', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: 'Добавить' }));
		const nameInput = screen.getByRole('textbox', { name: 'Наименование' });
		await user.type(nameInput, 'x');
		await user.keyboard('{Escape}');

		await waitFor(() =>
			expect(screen.queryByRole('textbox', { name: 'Наименование' })).not.toBeInTheDocument(),
		);
	});
});
