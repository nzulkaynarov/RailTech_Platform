import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';
import { VIRTUALIZE_THRESHOLD } from '@/components/QuoteBuilder/gridConstants';

/**
 * FIX-44 (F-7) — repro. REAL useMediaQuery, matchMedia emulates a 390 px phone.
 * волна 3 — the line table windows (virtualizes) its rows only ABOVE VIRTUALIZE_THRESHOLD.
 *   • a large КП renders only a window of rows into the DOM (not every line), proving windowing;
 *   • a small КП renders every row (the non-virtualized path, byte-identical to before).
 * The keyboard scroll-then-focus bridge is covered as a pure unit in gridScrollFocus.test.ts —
 * jsdom has no layout engine, so the actual scroll/measure math is not asserted here.
 */

let serverItems: QuoteItem[] | undefined = [];
let serverDeal: Deal | undefined;
// Сколько раз грид перерисовался (по вызовам useQuoteItems) и с какого вызова «сеть» отвечает —
// предохранитель: цикл рендера в тесте не должен уйти в бесконечность и убить процесс по памяти.
let itemsQueryCalls = 0;
let answerAfterCalls = Infinity;
const STABLE_EMPTY: QuoteItem[] = [];

vi.mock('@/hooks/useCRM', () => ({
	useQuoteItems: () => {
		itemsQueryCalls += 1;
		return { data: itemsQueryCalls > answerAfterCalls ? STABLE_EMPTY : serverItems, isLoading: false };
	},
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


/** matchMedia that evaluates `(max-width: Npx)` / `(min-width: Npx)` against a fixed viewport. */
function mockViewport(width: number) {
	window.matchMedia = vi.fn().mockImplementation((query: string) => {
		const max = /max-width:\s*(\d+)px/.exec(query);
		const min = /min-width:\s*(\d+)px/.exec(query);
		const matches = (max ? width <= Number(max[1]) : true) && (min ? width >= Number(min[1]) : true);
		return {
			matches, media: query, onchange: null,
			addListener: vi.fn(), removeListener: vi.fn(),
			addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
		};
	});
}

describe('QuoteBuilderGrid — F-7 «Maximum update depth» (390 px и ожидание сделки)', () => {
	const originalMatchMedia = window.matchMedia;
	let errorSpy: ReturnType<typeof vi.spyOn>;
	beforeEach(() => {
		mockViewport(390);
		itemsQueryCalls = 0;
		answerAfterCalls = Infinity;
		errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
	});
	afterEach(() => {
		window.matchMedia = originalMatchMedia;
		errorSpy.mockRestore();
	});
	const depthErrors = () => errorSpy.mock.calls.filter((c: unknown[]) => String(c[0]).includes('Maximum update depth'));

	it.each([
		['a small КП', 10],
		['a virtualized КП', VIRTUALIZE_THRESHOLD + 70],
	])('renders %s without a render loop', (_name, rowCount) => {
		serverItems = makeItems(rowCount);
		expect(() => renderWithProviders(<QuoteBuilderGrid dealId={42} />)).not.toThrow();
		expect(depthErrors()).toHaveLength(0);
		expect(qtyCellCount()).toBeGreaterThan(0);
	});

	// Причина F-7 (FIX-44). Пока сделка не приехала, активного КП нет → запрос позиций выключен и
	// `data === undefined`. Деструктуризация `{ data: quoteItems = [] }` подставляла НОВЫЙ `[]` на каждый
	// рендер; он уходил в `useQuoteDraft(serverItems)`, чей эффект зависит от `serverItems`, и вызывал
	// `setDraftItems(<новый массив>)` → рендер → новый `[]` → эффект… Цикл крутился, пока не придёт
	// сделка (на медленной сети — десятки кадров), и React в dev-режиме писал «Maximum update depth».
	it('does not loop while the deal (and so the items query) has not arrived', () => {
		serverDeal = undefined;
		serverItems = undefined; // query disabled → no data
		answerAfterCalls = 300; // «сеть» отвечает на 300-м рендере — иначе цикл не кончится
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);
		expect(itemsQueryCalls).toBeLessThan(20); // ожидаем 1–3 рендера, а не лавину
		expect(depthErrors()).toHaveLength(0);
	});
});
