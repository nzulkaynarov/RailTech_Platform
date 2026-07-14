import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { Deal, QuoteItem } from '@/api/crmApi';
import { QuoteBuilderGrid } from '@/components/Admin/QuoteBuilderGrid';
import {
	useDeal, useQuoteItems, useUpdateQuoteItem, useBulkUpdateQuoteItems, useCreateQuoteItem,
	useDeleteQuoteItem, useSetQuoteDeliveryBasis,
} from '@/hooks/useCRM';

/**
 * WP-C — the КП workspace groups the two document surfaces into Tabs so «Расходы и скидки»
 * no longer sits under the table costing vertical budget. Default tab is «Позиции»; switching
 * mounts the charges surface and the line table steps aside.
 */
vi.mock('@/hooks/useCRM', () => ({
	useDeal: vi.fn(),
	useQuoteItems: vi.fn(),
	useUpdateQuoteItem: vi.fn(),
	useBulkUpdateQuoteItems: vi.fn(),
	useCreateQuoteItem: vi.fn(),
	useDeleteQuoteItem: vi.fn(),
	useSetQuoteDeliveryBasis: vi.fn(),
}));
vi.mock('@/hooks/useMasterData', () => ({ useCurrencies: () => ({ data: [{ id: 1, code: 'UZS' }] }) }));
vi.mock('@/hooks/use-mobile', () => ({ useMediaQuery: () => false }));

// The charges surface is stubbed to a marker so we can assert it mounts only on its tab.
vi.mock('@/components/CRM/QuoteChargesSection', () => ({
	QuoteChargesSection: () => <div data-testid="charges-surface">charges</div>,
}));
vi.mock('@/components/CRM/DeliveryBasisSelect', () => ({ DeliveryBasisSelect: () => null }));
vi.mock('@/components/CRM/QuoteSettingsDialog', () => ({ QuoteSettingsDialog: () => null }));
vi.mock('@/components/CRM/ReassignProductDialog', () => ({ ReassignProductDialog: () => null }));
vi.mock('@/components/CRM/GenerateQuoteDialog', () => ({ GenerateQuoteDialog: () => null }));
vi.mock('@/components/Admin/AICatalogMatchDialog', () => ({ AICatalogMatchDialog: () => null }));
vi.mock('@/components/Shared/DocumentActions', () => ({ DocumentActions: () => null }));

const setHook = (hook: unknown, value: unknown) => { (hook as Mock).mockReturnValue(value); };
const mkMutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false });

const gridDeal = {
	id: 7,
	active_quote: {
		id: 200,
		quote_currency: 'UZS',
		vat_rate: '12',
		margin_percent: '20',
		cost_currency_default: 'UZS',
		delivery_basis: null,
		frozen_at: null,
		fx_snapshot: {},
		fx_manual: {},
		charges: [{ id: 1 }, { id: 2 }],
		charges_total: '0',
		subtotal_excl_vat: '120',
		vat_amount: '14.4',
		total_incl_vat: '134.4',
		effective_delivery_lead_time_days: 0,
		economics: null,
	},
} as unknown as Deal;

const gridItem = {
	id: 1,
	product: 1,
	product_name: 'Рельс Р65',
	product_sku: 'SKU-1',
	quantity: 1,
	frozen_base_price: '100',
	frozen_currency: 'UZS',
	customs_duty: '0',
	discount_percent: '0',
	lead_time_days: 0,
	hs_code: '',
	margin_percent: '0',
	landed_cost: '100',
	final_price_excl_vat: '120',
	offer_supplier_name: 'ООО Поставщик',
} as unknown as QuoteItem;

describe('QuoteBuilderGrid — document tabs', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		setHook(useDeal, { data: gridDeal, isLoading: false });
		setHook(useQuoteItems, { data: [gridItem], isLoading: false });
		[useUpdateQuoteItem, useBulkUpdateQuoteItems, useCreateQuoteItem, useDeleteQuoteItem, useSetQuoteDeliveryBasis]
			.forEach((hook) => setHook(hook, mkMutation()));
	});

	it('renders both tabs, with a count badge on «Расходы и скидки»', () => {
		renderWithProviders(<QuoteBuilderGrid dealId={7} />);

		expect(screen.getByRole('tab', { name: /Позиции/ })).toBeInTheDocument();
		const chargesTab = screen.getByRole('tab', { name: /Расходы и скидки/ });
		expect(chargesTab).toBeInTheDocument();
		expect(chargesTab).toHaveTextContent('2');
	});

	it('defaults to «Позиции» (line table visible, charges surface not mounted)', () => {
		renderWithProviders(<QuoteBuilderGrid dealId={7} />);

		// The line name renders in the table; the charges surface is on the inactive tab.
		expect(screen.getByText('Рельс Р65')).toBeInTheDocument();
		expect(screen.queryByTestId('charges-surface')).toBeNull();
	});

	it('switches to «Расходы и скидки» and mounts the charges surface', async () => {
		const user = userEvent.setup();
		renderWithProviders(<QuoteBuilderGrid dealId={7} />);

		await user.click(screen.getByRole('tab', { name: /Расходы и скидки/ }));

		await waitFor(() => {
			expect(screen.getByTestId('charges-surface')).toBeInTheDocument();
		});
		// The line table is no longer mounted on the charges tab.
		expect(screen.queryByText('Рельс Р65')).toBeNull();
	});
});
