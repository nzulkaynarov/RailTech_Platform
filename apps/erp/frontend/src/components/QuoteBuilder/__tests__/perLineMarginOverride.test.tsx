import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderHook } from '@testing-library/react';
import { toast } from 'sonner';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';
import {
	usePricingMirror, resolveEffectiveMarginPercent, hasMarginOverride,
	type PricingMirrorInput,
} from '@/components/QuoteBuilder/usePricingMirror';

/**
 * DT1 — per-line margin override, FRONTEND half.
 *
 * The backend (branch `feat/dt1-per-line-margin`) made `QuoteItem.margin_percent` nullable with
 * Salesforce-CPQ / Odoo semantics: NULL = «наследовать маржу КП», any non-null value = an explicit
 * per-line override that beats the quote margin — INCLUDING an explicit `0`, which genuinely means
 * «продать по себестоимости». Before that, the column was a NOT NULL default the engine ignored.
 *
 * Two failure modes are worth more than all the others combined, and both are covered below:
 *
 *  1. WRITE — clearing the cell must send `margin_percent: null`, never `0`. Sending `0` would be
 *     accepted by the serializer and would silently reprice the line down to cost. There is no
 *     error, no warning, and the seller only finds out when the client reads the КП.
 *  2. PREVIEW — `usePricingMirror` must mirror the backend precedence per line. It used to apply
 *     the quote-level markup to EVERY line, so an overridden line previewed the wrong «Сумма»
 *     until the save round-tripped — in the surface the codebase itself calls «деньги до копейки».
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

// Wide viewport → the cost columns (and therefore the margin column) render.
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

/** КП markup = 20 % — the rate an inheriting line must price at. */
function makeQuote(): Quote {
	return {
		id: 100, deal: 42, version: 1, status: 1, status_code: 'DRAFT', status_name: 'Черновик',
		quote_currency: 'UZS', cost_currency_default: 'UZS', vat_rate: '12', margin_percent: '20',
		fx_snapshot: {}, fx_manual: {}, items: [], charges: [],
		subtotal_excl_vat: '1200', charges_total: '0', vat_amount: '144', total_incl_vat: '1344',
		frozen_at: null,
		economics: {
			total_landed_cost: '1000', gross_profit: '200', gross_margin_percent: '16.7',
			markup_percent: '20', charge_cost_total: '0', operating_profit: '200',
			below_cost: false, below_floor: false, min_margin_percent: '5',
			target_margin_percent: '25', fx_missing: [],
		},
		created_at: '2026-07-01T00:00:00Z',
	} as Quote;
}

function makeItem(id: number, overrides: Partial<QuoteItem> = {}): QuoteItem {
	return {
		id, quote: 100, display_type: 'ITEM', is_optional: false, position: id,
		imported_raw_name: `Позиция ${id}`, quantity: 1,
		frozen_base_price: '1000', frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '0',
		margin_percent: null, discount_percent: '0', lead_time_days: 0,
		landed_cost: '1000', final_price_excl_vat: '1200', version: 1,
		...overrides,
	} as QuoteItem;
}

const MARGIN_CELL = 'Наценка позиции 1';
const REVERT_BUTTON = 'Вернуть наценку КП для позиции 1';

beforeEach(() => {
	bulkMutateAsync.mockReset().mockResolvedValue([]);
	vi.mocked(toast.success).mockReset();
	serverDeal = { id: 42, active_quote: makeQuote(), created_at: '2026-07-01T00:00:00Z' } as Deal;
	serverItems = [makeItem(1)];
});

/** The `margin_percent` the Save payload carried for row 1. */
async function savedMarginOf(): Promise<unknown> {
	await waitFor(() => expect(bulkMutateAsync).toHaveBeenCalledTimes(1));
	const payload = bulkMutateAsync.mock.calls[0][0];
	const row = payload.items.find((item: { id: number }) => item.id === 1);
	return row.margin_percent;
}

describe('DT1 write path — the cleared cell must send null, NEVER 0', () => {
	it('clearing an override sends margin_percent: null (inherit), not 0 (sell at cost)', async () => {
		const user = userEvent.setup();
		// Start from a line that HAS an override, so there is something to clear.
		serverItems = [makeItem(1, { margin_percent: '35' })];
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const cell = screen.getByRole('textbox', { name: MARGIN_CELL });
		expect(cell).toHaveValue('35');
		await user.clear(cell);
		await user.tab(); // blur → commit
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));

		const saved = await savedMarginOf();
		// THE assertion of this feature. `null` restores inheritance; `0` would silently reprice
		// the line to cost with no error anywhere in the stack.
		expect(saved).toBeNull();
		expect(saved).not.toBe('0');
		expect(saved).not.toBe(0);
	});

	it('the one-click revert control takes the same null path as clearing the cell', async () => {
		const user = userEvent.setup();
		serverItems = [makeItem(1, { margin_percent: '35' })];
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: REVERT_BUTTON }));
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));

		expect(await savedMarginOf()).toBeNull();
	});

	it('an EXPLICIT 0 typed by the seller is preserved as 0 — it is a real override', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		const cell = screen.getByRole('textbox', { name: MARGIN_CELL });
		await user.type(cell, '0');
		await user.tab();
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));

		// «Продать по себестоимости» must survive the round trip verbatim. If the write path
		// normalised falsy-looking values to null, this line would quietly go back to 20 %.
		const saved = await savedMarginOf();
		expect(saved).toBe('0');
		expect(saved).not.toBeNull();
	});

	it('a typed non-zero override is sent as that value', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.type(screen.getByRole('textbox', { name: MARGIN_CELL }), '42');
		await user.tab();
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));

		expect(await savedMarginOf()).toBe('42');
	});

	it('clamps a fat-finger above the backend cap (0–500) instead of round-tripping a 400', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.type(screen.getByRole('textbox', { name: MARGIN_CELL }), '9999');
		await user.tab();
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));

		expect(await savedMarginOf()).toBe('500');
		expect(toast.warning).toHaveBeenCalled();
	});

	it('an untouched inheriting line is not made dirty — nothing to save', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Focus and leave WITHOUT typing: an empty nullable cell that was already empty must not
		// register a change, or every visited row would be pushed on the next Save.
		await user.click(screen.getByRole('textbox', { name: MARGIN_CELL }));
		await user.tab();
		await user.click(screen.getByRole('button', { name: 'Сохранить' }));

		expect(bulkMutateAsync).not.toHaveBeenCalled();
	});
});

describe('DT1 preview — usePricingMirror mirrors the backend precedence per line', () => {
	const baseInput = (overrides: Partial<PricingMirrorInput> = {}): PricingMirrorInput => ({
		draftItems: [],
		dirtyIds: new Set(),
		marginPercent: '20', // КП-level markup
		vatRate: '12',
		fxSnapshot: {},
		fxManual: {},
		fxMarket: {},
		charges: [],
		canViewCost: true,
		minMarginPercent: null,
		serverTotals: {
			subtotalExclVat: '0', chargesTotal: '0', vatAmount: '0', totalInclVat: '0',
			grossMarginPercent: null,
		},
		...overrides,
	});

	it('resolveEffectiveMarginPercent follows override → quote → 0, and 0 is an override', () => {
		// Per-line override wins…
		expect(resolveEffectiveMarginPercent('35', '20').toString()).toBe('35');
		// …including an explicit zero, which is the entire reason the column became nullable.
		expect(resolveEffectiveMarginPercent('0', '20').toString()).toBe('0');
		// null/undefined/'' = no override → inherit the КП rate.
		expect(resolveEffectiveMarginPercent(null, '20').toString()).toBe('20');
		expect(resolveEffectiveMarginPercent(undefined, '20').toString()).toBe('20');
		expect(resolveEffectiveMarginPercent('', '20').toString()).toBe('20');
		// Neither level available → 0, matching the backend's final fallback.
		expect(resolveEffectiveMarginPercent(null, null).toString()).toBe('0');
		// Unparseable junk falls THROUGH rather than being read as a 0 override (toDecimal would
		// have mapped it to 0 and silently priced the line at cost).
		expect(resolveEffectiveMarginPercent('abc', '20').toString()).toBe('20');
	});

	it('hasMarginOverride treats 0 as an override but null/empty as inheritance', () => {
		expect(hasMarginOverride({ margin_percent: '0' })).toBe(true);
		expect(hasMarginOverride({ margin_percent: '35' })).toBe(true);
		expect(hasMarginOverride({ margin_percent: null })).toBe(false);
	});

	it('prices a dirty INHERITING line at the quote rate and an OVERRIDDEN line at its own', () => {
		// cost 1000 UZS each. Inheriting → ×1.20 = 1200. Override 50 % → ×1.50 = 1500.
		const inheriting = makeItem(1, { margin_percent: null });
		const overridden = makeItem(2, { margin_percent: '50' });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [inheriting, overridden],
				dirtyIds: new Set([1, 2]),
			})),
		);

		const inheritedLine = result.current.lineFor(inheriting);
		expect(inheritedLine.finalPriceExclVat).toBe('1200');
		expect(inheritedLine.effectiveMarginPercent).toBe('20');
		expect(inheritedLine.isMarginOverridden).toBe(false);

		const overriddenLine = result.current.lineFor(overridden);
		// Pre-DT1 this hook applied the quote's 20 % here too and previewed 1200 — a wrong number
		// in the money column until the server replied.
		expect(overriddenLine.finalPriceExclVat).toBe('1500');
		expect(overriddenLine.effectiveMarginPercent).toBe('50');
		expect(overriddenLine.isMarginOverridden).toBe(true);
	});

	it('prices an explicit 0 override at cost, not at the inherited quote rate', () => {
		const atCost = makeItem(1, { margin_percent: '0' });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({ draftItems: [atCost], dirtyIds: new Set([1]) })),
		);

		const line = result.current.lineFor(atCost);
		expect(line.finalPriceExclVat).toBe('1000'); // == landed cost
		expect(line.marginPct).toBe(0);
		expect(line.isMarginOverridden).toBe(true);
	});

	it('folds the per-line rates into the КП subtotal (not one blanket quote rate)', () => {
		const inheriting = makeItem(1, { margin_percent: null });
		const overridden = makeItem(2, { margin_percent: '50' });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({
				draftItems: [inheriting, overridden],
				dirtyIds: new Set([1, 2]),
			})),
		);

		expect(result.current.totals.computable).toBe(true);
		// 1200 + 1500 — a blanket 20 % would have produced 2400.
		expect(result.current.totals.subtotalExclVat).toBe('2700');
	});

	it('reports the effective rate even when the price preview is withheld (unknown FX)', () => {
		// A non-UZS line with no rate on ANY map: cost/price are withheld (needsServerRecalc), but
		// WHICH markup applies is independent of FX, so the margin cell must still render it.
		const unknownFx = makeItem(1, { frozen_currency: 'EUR', margin_percent: '35' });
		const { result } = renderHook(() =>
			usePricingMirror(baseInput({ draftItems: [unknownFx], dirtyIds: new Set([1]) })),
		);

		const line = result.current.lineFor(unknownFx);
		expect(line.needsServerRecalc).toBe(true);
		expect(line.effectiveMarginPercent).toBe('35');
		expect(line.isMarginOverridden).toBe(true);
	});
});
