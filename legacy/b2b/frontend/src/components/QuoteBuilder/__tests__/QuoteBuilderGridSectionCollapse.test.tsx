import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { toast } from 'sonner';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, Quote, QuoteItem } from '@/api/crmApi';

/**
 * U5 (спека §5) — collapsible sections in the КП builder:
 *   • a chevron on a SECTION heading collapses/expands the group;
 *   • a collapsed section removes its child rows from the RENDERED (virtualized) list, not via
 *     display:none — the children genuinely leave `visibleItems`;
 *   • the collapsed heading keeps showing the Σ подытог of its children;
 *   • the collapsed set persists to localStorage (`kp.sections.collapsed`);
 *   • expanding restores the children.
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
		subtotal_excl_vat: '2400', charges_total: '0', vat_amount: '288', total_incl_vat: '2688',
		frozen_at: null,
		economics: {
			total_landed_cost: '1600', gross_profit: '800', gross_margin_percent: '33',
			markup_percent: '25', charge_cost_total: '0', operating_profit: '800',
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

// Item #1 stands alone; SECTION #2 groups ITEM #3 + ITEM #4 (each 400 × 2 = 800 → Σ 1600).
function makeSectionedItems(): QuoteItem[] {
	return [
		makeItem(1, { position: 1 }),
		makeItem(2, { display_type: 'SECTION', imported_raw_name: 'Механика', position: 2 }),
		makeItem(3, { position: 3 }),
		makeItem(4, { position: 4 }),
	];
}

const digitsOf = (text: string | null | undefined): string => (text ?? '').replace(/\D/g, '');

beforeEach(() => {
	localStorage.clear();
	bulkMutateAsync.mockReset().mockResolvedValue([]);
	createMutateAsync.mockReset().mockResolvedValue(makeItem(9));
	updateMutateAsync.mockReset().mockResolvedValue(makeItem(1));
	vi.mocked(toast.success).mockReset();
	vi.mocked(toast.error).mockReset();
	serverItems = makeSectionedItems();
	serverDeal = { id: 42, active_quote: makeQuote(), created_at: '2026-07-01T00:00:00Z' } as Deal;
});

describe('QuoteBuilderGrid — collapsible sections (U5)', () => {
	it('collapsing a section removes its child rows from the rendered list', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Three ITEM rows initially expose a qty cell (items 1, 3, 4).
		expect(screen.getAllByRole('textbox', { name: 'Кол-во' })).toHaveLength(3);

		await user.click(screen.getByRole('button', { name: 'Свернуть раздел' }));

		// The section's two children (3, 4) leave the list; only the standalone item 1 remains.
		await waitFor(() => expect(screen.getAllByRole('textbox', { name: 'Кол-во' })).toHaveLength(1));
		// The SECTION heading itself stays visible — it's the control that re-expands the group.
		expect(screen.getByRole('button', { name: 'Развернуть раздел' })).toBeInTheDocument();
	});

	it('expanding a collapsed section restores its children', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: 'Свернуть раздел' }));
		await waitFor(() => expect(screen.getAllByRole('textbox', { name: 'Кол-во' })).toHaveLength(1));

		await user.click(screen.getByRole('button', { name: 'Развернуть раздел' }));
		await waitFor(() => expect(screen.getAllByRole('textbox', { name: 'Кол-во' })).toHaveLength(3));
	});

	it('a collapsed section still shows the Σ подытог of its children on the heading', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		await user.click(screen.getByRole('button', { name: 'Свернуть раздел' }));
		await waitFor(() => expect(screen.getByRole('button', { name: 'Развернуть раздел' })).toBeInTheDocument());

		// The SECTION row's own text carries the subtotal label + its Σ (1600 → «1 600,00»).
		const sectionRow = document.querySelector('[data-display-type="SECTION"]');
		expect(sectionRow).not.toBeNull();
		expect(sectionRow?.textContent).toContain('Подытог');
		// Currency separators are locale-dependent, so compare on digits only: 1600.00 → 160000.
		expect(digitsOf(sectionRow?.textContent)).toContain('160000');
	});

	it('the collapsed set persists to localStorage', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		expect(localStorage.getItem('kp.sections.collapsed')).toBeNull();
		await user.click(screen.getByRole('button', { name: 'Свернуть раздел' }));

		// SECTION row id 2 is persisted.
		await waitFor(() =>
			expect(JSON.parse(localStorage.getItem('kp.sections.collapsed') ?? '[]')).toEqual([2]),
		);

		// Expanding clears it again.
		await user.click(screen.getByRole('button', { name: 'Развернуть раздел' }));
		await waitFor(() =>
			expect(JSON.parse(localStorage.getItem('kp.sections.collapsed') ?? '[]')).toEqual([]),
		);
	});

	it('restores the collapsed state from localStorage on mount', async () => {
		localStorage.setItem('kp.sections.collapsed', JSON.stringify([2]));
		renderWithProviders(<QuoteBuilderGrid dealId={42} />);

		// Section 2 starts collapsed → its two children are absent, and the heading shows «expand».
		expect(screen.getAllByRole('textbox', { name: 'Кол-во' })).toHaveLength(1);
		expect(screen.getByRole('button', { name: 'Развернуть раздел' })).toBeInTheDocument();
	});
});
