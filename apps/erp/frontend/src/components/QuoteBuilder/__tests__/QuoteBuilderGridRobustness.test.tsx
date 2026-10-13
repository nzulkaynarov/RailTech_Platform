import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';

/**
 * Волна B — робастность грида (B3 / DT4 / DT7 / DT9).
 *
 * Covers the parts of the wave that jsdom CAN prove:
 *   • DT7 — Shift+click range selection still works through the semantic `onCheckedChange`
 *     path (the `onClick` + `event.shiftKey` cast is gone);
 *   • DT4 — pricing-assist issues ONE bulk-update (not N sequential PATCHes) and deliberately
 *     omits `version`, preserving the last-write-wins semantics the per-row PATCHes had;
 *   • DT9 — a bulk price change that hits the 0..cap bounds raises a clamp toast;
 *   • DT4 — `GridRow` is wrapped in `React.memo`.
 *
 * The virtualization BEHAVIOUR of B3 (scroll-to-top on click, drift on expand) cannot be
 * asserted here — jsdom computes no layout, so every element measures 0×0 and the
 * virtualizer never windows for real. Its structural invariant (exactly one `data-index`
 * node per line) is asserted in QuoteBuilderGridVirtualize.test.tsx instead.
 */

const bulkUpdateMutateAsync = vi.fn();
const updateMutateAsync = vi.fn();
const pricingAssist = vi.fn();

let serverItems: QuoteItem[] = [];
let serverDeal: Deal | undefined;

vi.mock('@/hooks/useCRM', () => ({
	useQuoteItems: () => ({ data: serverItems, isLoading: false }),
	useDeal: () => ({ data: serverDeal, isLoading: false }),
	useUpdateQuoteItem: () => ({ mutateAsync: updateMutateAsync, isPending: false }),
	useBulkUpdateQuoteItems: () => ({ mutateAsync: bulkUpdateMutateAsync, isPending: false }),
	useBulkCreateQuoteItems: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useBulkDeleteQuoteItems: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useCreateQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useDeleteQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useSetQuoteDeliveryBasis: () => ({ mutate: vi.fn(), isPending: false }),
	useReassignProduct: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/api/crmApi', async (importOriginal) => ({
	...(await importOriginal<typeof import('@/api/crmApi')>()),
	crmApi: { pricingAssist: (...args: unknown[]) => pricingAssist(...args) },
}));

vi.mock('@/hooks/useMasterData', () => ({
	useCurrencies: () => ({ data: [{ id: 1, code: 'UZS' }, { id: 2, code: 'USD' }] }),
}));

// Wide viewport → the cost columns render.
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
import { GridRow } from '@/components/QuoteBuilder/GridRow';

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

function makeItem(id: number, name: string, price: string, version = 7): QuoteItem {
	return {
		id, quote: 100, imported_raw_name: name, quantity: 1, version,
		frozen_base_price: price, frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '0',
		margin_percent: '0', discount_percent: '0', lead_time_days: 0,
		landed_cost: price, final_price_excl_vat: price,
	} as QuoteItem;
}

beforeEach(() => {
	bulkUpdateMutateAsync.mockReset();
	updateMutateAsync.mockReset();
	pricingAssist.mockReset();
	vi.mocked(toast.success).mockReset();
	vi.mocked(toast.warning).mockReset();
	vi.mocked(toast.error).mockReset();
	serverItems = [
		makeItem(1, 'Болт М12', '1000'),
		makeItem(2, 'Гайка М12', '2000'),
		makeItem(3, 'Шайба М12', '3000'),
		makeItem(4, 'Шпилька М12', '4000'),
	];
	serverDeal = { id: 42, active_quote: makeQuote(), created_at: '2026-07-01T00:00:00Z' } as Deal;
});

describe('DT7 — row selection via onCheckedChange', () => {
	it('a plain click toggles exactly one row', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('checkbox', { name: 'Выбрать позицию 2' }));
		expect(screen.getByText('Выбрано: 1')).toBeInTheDocument();
	});

	it('Shift+click selects the whole range between the anchor and the clicked row', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Anchor on row 1, then Shift+click row 4 → rows 1..4 are all selected.
		await user.click(screen.getByRole('checkbox', { name: 'Выбрать позицию 1' }));
		await user.keyboard('{Shift>}');
		await user.click(screen.getByRole('checkbox', { name: 'Выбрать позицию 4' }));
		await user.keyboard('{/Shift}');

		expect(screen.getByText('Выбрано: 4')).toBeInTheDocument();
	});

	it('the Shift flag does not leak into the NEXT plain click', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('checkbox', { name: 'Выбрать позицию 1' }));
		await user.keyboard('{Shift>}');
		await user.click(screen.getByRole('checkbox', { name: 'Выбрать позицию 3' }));
		await user.keyboard('{/Shift}');
		expect(screen.getByText('Выбрано: 3')).toBeInTheDocument();

		// A plain click on row 4 must ADD one row, not extend a range from the stale anchor.
		await user.click(screen.getByRole('checkbox', { name: 'Выбрать позицию 4' }));
		expect(screen.getByText('Выбрано: 4')).toBeInTheDocument();
	});
});

describe('DT4 — pricing-assist uses ONE bulk update', () => {
	it('collapses N suggestions into a single versionless bulk-update payload', async () => {
		pricingAssist.mockResolvedValue({
			suggestions: [
				{ item_id: 1, base_price: '1111', currency: 'USD', lead_time_days: 10 },
				{ item_id: 2, base_price: '2222', currency: null, lead_time_days: 20 },
			],
		});
		bulkUpdateMutateAsync.mockResolvedValue([]);
		// The toolbar only offers pricing-assist once ≥1 line is bound to a catalog product.
		serverItems = [
			{ ...makeItem(1, 'Болт М12', '1000'), product: 55 } as QuoteItem,
			makeItem(2, 'Гайка М12', '2000'),
		];
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: 'Цены из офферов' }));

		await waitFor(() => expect(bulkUpdateMutateAsync).toHaveBeenCalledTimes(1));
		// The old per-row loop is gone — no single-item PATCH is issued at all.
		expect(updateMutateAsync).not.toHaveBeenCalled();

		const payload = bulkUpdateMutateAsync.mock.calls[0][0];
		expect(payload.quoteId).toBe(100);
		expect(payload.items).toEqual([
			{ id: 1, frozen_base_price: '1111', frozen_currency: 'USD', lead_time_days: 10 },
			{ id: 2, frozen_base_price: '2222', frozen_currency: undefined, lead_time_days: 20 },
		]);
		// `version` is deliberately ABSENT: pricing-assist keeps last-write-wins, so it can never
		// answer 409 QUOTE_ITEM_STALE (there is no conflict branch for it).
		for (const item of payload.items) expect(item).not.toHaveProperty('version');
	});

	it('an empty suggestion list issues no write at all', async () => {
		pricingAssist.mockResolvedValue({ suggestions: [] });
		// The toolbar only offers pricing-assist once ≥1 line is bound to a catalog product.
		serverItems = [
			{ ...makeItem(1, 'Болт М12', '1000'), product: 55 } as QuoteItem,
			makeItem(2, 'Гайка М12', '2000'),
		];
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: 'Цены из офферов' }));

		await waitFor(() => expect(toast.info).toHaveBeenCalled());
		expect(bulkUpdateMutateAsync).not.toHaveBeenCalled();
	});
});

describe('DT9 — bulk price change clamp is announced', () => {
	it('warns when a computed price is clamped to the allowed cap', async () => {
		// A +900% change on a 4 000 000 000 line overshoots QUOTE_ITEM_MAX_UNIT_PRICE.
		serverItems = [makeItem(1, 'Дорогая позиция', '4000000000')];
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('checkbox', { name: 'Выбрать позицию 1' }));
		await user.click(screen.getByRole('button', { name: 'Изменить цену' }));
		await user.type(await screen.findByRole('textbox', { name: 'Изменение цены, %' }), '900');
		await user.click(screen.getByRole('button', { name: 'Применить' }));

		await waitFor(() =>
			expect(toast.warning).toHaveBeenCalledWith('Некоторые значения скорректированы до допустимых границ'),
		);
	});

	it('stays silent when nothing is clamped', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('checkbox', { name: 'Выбрать позицию 1' }));
		await user.click(screen.getByRole('button', { name: 'Изменить цену' }));
		// 1 000 → 1 100: comfortably inside 0..QUOTE_ITEM_MAX_UNIT_PRICE, nothing to clamp.
		await user.type(await screen.findByRole('textbox', { name: 'Изменение цены, %' }), '10');
		await user.click(screen.getByRole('button', { name: 'Применить' }));

		await waitFor(() => expect(toast.success).toHaveBeenCalled());
		expect(toast.warning).not.toHaveBeenCalled();
	});
});

describe('DT4 — GridRow memoization', () => {
	it('GridRow is wrapped in React.memo, so a scroll-driven GridTable re-render skips untouched rows', () => {
		expect((GridRow as unknown as { $$typeof: symbol }).$$typeof).toBe(Symbol.for('react.memo'));
	});
});
