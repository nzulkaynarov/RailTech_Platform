import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';

/**
 * Wave D — U1 (reorder ITEM rows) and U4 (find/filter inside a long КП).
 *
 * U1: product rows had neither ↑/↓ nor drag; only SECTION/NOTE could be moved. They now reuse the
 * SAME position-swap bulk-update — INCLUDING its save-before-move guard, which must not regress:
 * the swap bumps both rows' server version, and a row with unsaved edits keeps its stale version
 * locally, so an unguarded move would false-409 the next Save and the conflict reload would throw
 * that edit away.
 *
 * U4: the filter narrows what the TABLE renders and nothing else — the totals, the margin and the
 * save payload keep reading the full document.
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

import { QuoteBuilderGrid } from '@/components/QuoteBuilder/QuoteBuilderGrid';

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
	vi.mocked(toast.warning).mockReset();
	serverItems = [
		makeItem(1, { position: 1, imported_raw_name: 'Рельс Р65' }),
		makeItem(2, { position: 2, imported_raw_name: 'Шпала ЖБ' }),
		makeItem(3, { position: 3, imported_raw_name: 'Рельс Р50' }),
	];
	serverDeal = { id: 42, active_quote: makeQuote(), created_at: '2026-07-01T00:00:00Z' } as Deal;
});

describe('U1 — reordering ITEM rows', () => {
	it('every ITEM row exposes ↑/↓ (they used to exist only on SECTION/NOTE rows)', () => {
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		expect(screen.getAllByRole('button', { name: /Переместить позицию \d+ вверх/ })).toHaveLength(3);
		expect(screen.getAllByRole('button', { name: /Переместить позицию \d+ вниз/ })).toHaveLength(3);
	});

	it('↓ swaps `position` with the next row in ONE transactional bulk-update', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: 'Переместить позицию 1 вниз' }));
		await waitFor(() => expect(bulkMutateAsync).toHaveBeenCalledTimes(1));

		const payload = bulkMutateAsync.mock.calls[0][0];
		expect(payload.quoteId).toBe(100);
		// A clean swap, and each row echoes the version the grid last read (optimistic lock).
		expect(payload.items).toEqual(
			expect.arrayContaining([
				expect.objectContaining({ id: 1, position: 2, version: 1 }),
				expect.objectContaining({ id: 2, position: 1, version: 1 }),
			]),
		);
	});

	it('↑ swaps with the PREVIOUS row', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: 'Переместить позицию 3 вверх' }));
		await waitFor(() => expect(bulkMutateAsync).toHaveBeenCalledTimes(1));

		expect(bulkMutateAsync.mock.calls[0][0].items).toEqual(
			expect.arrayContaining([
				expect.objectContaining({ id: 3, position: 2 }),
				expect.objectContaining({ id: 2, position: 3 }),
			]),
		);
	});

	it('↑ is disabled on the first row and ↓ on the last', () => {
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		expect(screen.getByRole('button', { name: 'Переместить позицию 1 вверх' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Переместить позицию 3 вниз' })).toBeDisabled();
		// …and the interior handles stay live.
		expect(screen.getByRole('button', { name: 'Переместить позицию 2 вверх' })).toBeEnabled();
		expect(screen.getByRole('button', { name: 'Переместить позицию 2 вниз' })).toBeEnabled();
	});

	it('REGRESSION GUARD: a move whose swap partner has unsaved edits is blocked, not silently lost', async () => {
		// The swap bulk-update bumps BOTH versions; the dirty row keeps its stale version locally, so
		// an unguarded move would false-409 the next Save and the reload would discard the edit.
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Dirty row #2 (the down-swap partner of row #1) by toggling its «опция» flag.
		const optionalToggles = screen.getAllByRole('checkbox', { name: /Опциональная позиция/ });
		await user.click(optionalToggles[1]);
		await waitFor(() => expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument());

		await user.click(screen.getByRole('button', { name: 'Переместить позицию 1 вниз' }));

		expect(toast.warning).toHaveBeenCalledTimes(1);
		expect(bulkMutateAsync).not.toHaveBeenCalled();
	});

	it('the MOVING row having unsaved edits blocks it too (not only the neighbour)', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const optionalToggles = screen.getAllByRole('checkbox', { name: /Опциональная позиция/ });
		await user.click(optionalToggles[0]); // dirty row #1
		await waitFor(() => expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument());

		await user.click(screen.getByRole('button', { name: 'Переместить позицию 1 вниз' }));

		expect(toast.warning).toHaveBeenCalledTimes(1);
		expect(bulkMutateAsync).not.toHaveBeenCalled();
	});
});

describe('U4 — find/filter inside the КП', () => {
	const typeFilter = async (user: ReturnType<typeof userEvent.setup>, text: string) => {
		await user.type(screen.getByRole('searchbox', { name: 'Найти позицию в КП' }), text);
	};

	it('renders only the matching lines', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		expect(screen.getAllByRole('combobox', { name: /Наименование позиции/ })).toHaveLength(3);

		await typeFilter(user, 'рельс');

		await waitFor(() => expect(screen.getAllByRole('combobox', { name: /Наименование позиции/ })).toHaveLength(2));
		const names = screen.getAllByRole('combobox', { name: /Наименование позиции/ })
			.map((input) => (input as HTMLInputElement).value);
		expect(names).toEqual(['Рельс Р65', 'Рельс Р50']);
	});

	it('keeps each line NUMBERED by its place in the document, not by its place in the filtered view', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await typeFilter(user, 'р50'); // matches only the THIRD line

		// Its delete control still names it «позиция 3» — the seller is not lied to about the order.
		await waitFor(() => expect(screen.getByRole('button', { name: 'Удалить позицию 3' })).toBeInTheDocument());
		expect(screen.queryByRole('button', { name: 'Удалить позицию 1' })).not.toBeInTheDocument();
	});

	it('shows a match counter and an explicit «нет совпадений» row instead of an empty table', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await typeFilter(user, 'рельс');
		await waitFor(() => expect(screen.getByText('Найдено: 2 из 3')).toBeInTheDocument());

		await user.clear(screen.getByRole('searchbox', { name: 'Найти позицию в КП' }));
		await typeFilter(user, 'вагон');
		await waitFor(() => expect(screen.getByText(/Ничего не найдено/)).toBeInTheDocument());
	});

	it('does NOT change the document totals — the money is the whole КП, not the filtered view', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		const totalsBefore = screen.getByText('Позиций: 3');

		await typeFilter(user, 'р50'); // 1 of 3 visible

		await waitFor(() => expect(screen.getAllByRole('combobox', { name: /Наименование позиции/ })).toHaveLength(1));
		// Still «Позиций: 3» — the totals bar reports the DOCUMENT, not the view.
		expect(totalsBefore).toBeInTheDocument();
		expect(screen.getByText('Позиций: 3')).toBeInTheDocument();
	});

	it('does NOT drop a hidden dirty row from the save payload', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Edit row #2 («Шпала ЖБ»), then filter it OUT of view and save.
		const optionalToggles = screen.getAllByRole('checkbox', { name: /Опциональная позиция/ });
		await user.click(optionalToggles[1]);
		await waitFor(() => expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument());

		await typeFilter(user, 'рельс'); // «Шпала ЖБ» is now hidden
		await waitFor(() => expect(screen.getAllByRole('combobox', { name: /Наименование позиции/ })).toHaveLength(2));

		await user.click(screen.getByRole('button', { name: 'Сохранить' }));
		await waitFor(() => expect(bulkMutateAsync).toHaveBeenCalledTimes(1));
		// The hidden edit is still saved — filtering is a VIEW, never a scope for writes.
		expect(bulkMutateAsync.mock.calls[0][0].items).toEqual([
			expect.objectContaining({ id: 2, is_optional: true }),
		]);
	});

	it('disables reorder while filtered (a swap would move an invisible neighbour)', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		expect(screen.getByRole('button', { name: 'Переместить позицию 2 вниз' })).toBeEnabled();

		await typeFilter(user, 'рельс');

		await waitFor(() => expect(screen.getByRole('button', { name: 'Переместить позицию 1 вниз' })).toBeDisabled());
		expect(screen.getByRole('button', { name: 'Переместить позицию 3 вверх' })).toBeDisabled();
	});

	it('«выбрать все» under a filter selects only the VISIBLE rows', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await typeFilter(user, 'рельс');
		await waitFor(() => expect(screen.getAllByRole('combobox', { name: /Наименование позиции/ })).toHaveLength(2));

		await user.click(screen.getByRole('checkbox', { name: 'Выбрать все позиции' }));

		// 2 visible rows selected — not all 3 (a bulk delete must not take the hidden «Шпала ЖБ»).
		const selectionStrip = await screen.findByText('Выбрано: 2');
		expect(selectionStrip).toBeInTheDocument();
	});

	it('the clear (×) button empties the filter and restores every line', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await typeFilter(user, 'рельс');
		await waitFor(() => expect(screen.getAllByRole('combobox', { name: /Наименование позиции/ })).toHaveLength(2));

		await user.click(screen.getByRole('button', { name: 'Очистить поиск' }));

		await waitFor(() => expect(screen.getAllByRole('combobox', { name: /Наименование позиции/ })).toHaveLength(3));
	});
});

describe('U2 — one toolbar row', () => {
	it('the tabs live in the toolbar row and still switch panels', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const tabs = screen.getByRole('tablist');
		expect(within(tabs).getByRole('tab', { name: /Позиции/ })).toBeInTheDocument();

		await user.click(within(tabs).getByRole('tab', { name: /Расходы/ }));
		await waitFor(() => expect(within(tabs).getByRole('tab', { name: /Расходы/ })).toHaveAttribute('aria-selected', 'true'));
	});

	it('the bulk-action strip REPLACES the row actions in place instead of stacking a second strip', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		expect(screen.getByRole('button', { name: 'Добавить' })).toBeInTheDocument();

		await user.click(screen.getAllByRole('checkbox', { name: /Выбрать позицию/ })[0]);

		await waitFor(() => expect(screen.getByText('Выбрано: 1')).toBeInTheDocument());
		// The add/paste cluster gave way to the bulk strip — no second full-width row appeared.
		expect(screen.queryByRole('button', { name: 'Добавить' })).not.toBeInTheDocument();
		// The tabs and the view controls are untouched.
		expect(screen.getByRole('tablist')).toBeInTheDocument();
	});
});
