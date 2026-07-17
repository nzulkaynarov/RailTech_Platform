import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';
import { VIRTUALIZE_THRESHOLD } from '@/components/QuoteBuilder/gridConstants';

/**
 * волна 3 — the line table windows (virtualizes) its rows only ABOVE VIRTUALIZE_THRESHOLD.
 *   • a large КП renders only a window of rows into the DOM (not every line), proving windowing;
 *   • a small КП renders every row (the non-virtualized path, byte-identical to before).
 * The keyboard scroll-then-focus bridge is covered as a pure unit in gridScrollFocus.test.ts —
 * jsdom has no layout engine, so the actual scroll/measure math is not asserted here.
 */

let serverItems: QuoteItem[] = [];
let serverDeal: Deal | undefined;

vi.mock('@/hooks/useCRM', () => ({
	useQuoteItems: () => ({ data: serverItems, isLoading: false }),
	useDeal: () => ({ data: serverDeal, isLoading: false }),
	useUpdateQuoteItem: () => ({ mutateAsync: vi.fn(), isPending: false }),
	useBulkUpdateQuoteItems: () => ({ mutateAsync: vi.fn(), isPending: false }),
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

// Wide viewport → cost columns render; irrelevant to the row count but keeps the layout stable.
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

function makeItem(id: number): QuoteItem {
	return {
		id, quote: 100, imported_raw_name: `Позиция ${id}`, quantity: 1,
		frozen_base_price: '100', frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '0',
		margin_percent: '0', discount_percent: '0', lead_time_days: 0,
		landed_cost: '100', final_price_excl_vat: '120',
	} as QuoteItem;
}

const makeItems = (count: number): QuoteItem[] => Array.from({ length: count }, (_, index) => makeItem(index + 1));

const qtyCellCount = () => screen.getAllByRole('textbox', { name: 'Кол-во' }).length;

// jsdom has no layout engine: every element reports a 0×0 rect and the global ResizeObserver mock
// (src/test/setup.ts) never fires, so the virtualizer would measure a 0-height viewport and render
// an empty window. Here we (a) stub a fixed 800×400 rect and (b) swap in a ResizeObserver that
// fires once on observe — so the virtualizer receives a real, finite viewport and computes a real
// (bounded, < full-list) window. Exact sizes don't matter, only that the window is smaller than 120.
const FIXED_RECT = {
	width: 800, height: 400, top: 0, left: 0, right: 800, bottom: 400, x: 0, y: 0, toJSON: () => ({}),
} as DOMRect;

let rectSpy: ReturnType<typeof vi.spyOn>;
const OriginalResizeObserver = global.ResizeObserver;

class FiringResizeObserver {
	constructor(private callback: ResizeObserverCallback) {}
	observe(element: Element) {
		this.callback(
			[{
				target: element,
				contentRect: FIXED_RECT,
				borderBoxSize: [{ inlineSize: 800, blockSize: 400 }],
				contentBoxSize: [{ inlineSize: 800, blockSize: 400 }],
				devicePixelContentBoxSize: [{ inlineSize: 800, blockSize: 400 }],
			}] as unknown as ResizeObserverEntry[],
			this as unknown as ResizeObserver,
		);
	}
	unobserve() {}
	disconnect() {}
}

beforeEach(() => {
	serverDeal = { id: 42, active_quote: makeQuote(), created_at: '2026-07-01T00:00:00Z' } as Deal;
	rectSpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(FIXED_RECT);
	global.ResizeObserver = FiringResizeObserver as unknown as typeof ResizeObserver;
});

afterEach(() => {
	rectSpy.mockRestore();
	global.ResizeObserver = OriginalResizeObserver;
});

describe('QuoteBuilderGrid — virtualization threshold', () => {
	it(`renders every row at or below the threshold (${VIRTUALIZE_THRESHOLD})`, () => {
		const rowCount = 10; // well under the threshold → the non-virtualized path
		serverItems = makeItems(rowCount);
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Every line is in the DOM — no windowing.
		expect(qtyCellCount()).toBe(rowCount);
	});

	it('windows the rows above the threshold (not every line is in the DOM)', () => {
		const rowCount = VIRTUALIZE_THRESHOLD + 70; // 120 rows → virtualized
		serverItems = makeItems(rowCount);
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const rendered = qtyCellCount();
		// A window (plus overscan) is rendered — strictly fewer rows than the full list, but > 0.
		expect(rendered).toBeGreaterThan(0);
		expect(rendered).toBeLessThan(rowCount);
	});

	it('tags the expanded detail sub-row with the same data-index so the virtualizer measures it', () => {
		serverItems = makeItems(VIRTUALIZE_THRESHOLD + 70); // virtualized path
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Expand the first windowed line (index 0, id 1).
		fireEvent.click(screen.getAllByLabelText('Детализация позиции')[0]);

		// Both the main row AND its detail sub-row carry data-index=0 — so the virtualizer's
		// ResizeObserver measures the taller expanded group, not just the 44px main row.
		const mainRow = document.querySelector('[data-row-id="1"]');
		expect(mainRow).toHaveAttribute('data-index', '0');
		const detailRow = document.getElementById('kp-line-detail-1')?.closest('tr');
		expect(detailRow).toHaveAttribute('data-index', '0');
	});
});
