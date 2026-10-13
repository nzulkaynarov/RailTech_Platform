import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import type { QuoteItem } from '@/api/crmApi';
import type { Product } from '@/api/catalogApi';

/**
 * spec §5 п.13 — catalog typeahead in the КП name cell.
 *   • typing ≥2 chars opens the suggestion list (debounced catalog search);
 *   • picking a suggestion calls the EXISTING reassign (bind) mutation with the product id;
 *   • Escape closes the list WITHOUT binding;
 *   • free text + blur (no pick) does NOT bind;
 *   • ArrowUp/Down navigate suggestions ONLY while the list is open — when closed the
 *     keydown is not swallowed (bubbles to the grid's useGridKeyboard handler).
 */

const reassignMutateAsync = vi.fn().mockResolvedValue({});

// The catalog product fixtures the mocked search returns for any ≥2-char term.
const PRODUCTS: Product[] = [
	{
		id: 11, name: 'Рельс Р65', description: '', sku: 'R65', status: 1, status_name: 'Опубликован',
		domain_type: 1, domain_type_name: 'Оборудование', base_price: '0', gost_drawing: 'ГОСТ Р 51685',
		manufacturer_part_number: 'MPN-65',
	} as Product,
	{
		id: 22, name: 'Рельс Р50', description: '', sku: 'R50', status: 1, status_name: 'Опубликован',
		domain_type: 1, domain_type_name: 'Оборудование', base_price: '0', gost_drawing: 'ГОСТ 7174',
		manufacturer_part_number: 'MPN-50',
	} as Product,
];

// Debounce is identity in tests → the search term updates synchronously with typing.
vi.mock('@/hooks/useDebouncedValue', () => ({
	useDebouncedValue: (value: string) => value,
}));

// Reuse of the real catalog search endpoint is asserted by the query shape; here we mock the
// hook to return the fixtures whenever a ≥2-char term is passed (mirrors the `enabled` gate).
vi.mock('@/hooks/useCatalog', () => ({
	useProductSearch: (term: string) => ({
		data: term.trim().length >= 2 ? PRODUCTS : [],
		isFetching: false,
	}),
}));

// The bind path — SAME mutation ReassignProductDialog uses (reassign-product endpoint).
vi.mock('@/hooks/useCRM', () => ({
	useReassignProduct: () => ({ mutateAsync: reassignMutateAsync, isPending: false }),
}));

vi.mock('sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

import { ProductNameCell } from '@/components/QuoteBuilder/ProductNameCell';

function makeItem(overrides: Partial<QuoteItem> = {}): QuoteItem {
	return {
		id: 7,
		quote: 100,
		product: null,
		imported_raw_name: 'старое имя',
		quantity: 1,
		frozen_base_price: '0',
		frozen_currency: 'UZS',
		logistics_cost: '0',
		customs_duty: '0',
		margin_percent: '0',
		discount_percent: '0',
		lead_time_days: 0,
		landed_cost: '0',
		final_price_excl_vat: '0',
		...overrides,
	};
}

function renderCell(item: QuoteItem, onBrowse = vi.fn()) {
	return renderWithProviders(
		<ProductNameCell item={item} index={1} onBrowseCandidates={onBrowse} />,
	);
}

beforeEach(() => {
	vi.clearAllMocks();
});

describe('ProductNameCell typeahead', () => {
	it('opens the suggestion list on ≥2-char input', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.type(input, 'ре');

		await waitFor(() => expect(screen.getByRole('listbox')).toBeInTheDocument());
		expect(screen.getByText('Рельс Р65')).toBeInTheDocument();
		expect(screen.getByText('Рельс Р50')).toBeInTheDocument();
	});

	it('does not open on a single character', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.clear(input);
		await user.type(input, 'р');

		expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
	});

	it('binds the picked product via the reassign mutation', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.type(input, 'рельс');
		await waitFor(() => expect(screen.getByText('Рельс Р50')).toBeInTheDocument());
		await user.click(screen.getByText('Рельс Р50'));

		expect(reassignMutateAsync).toHaveBeenCalledWith({ quoteItemId: 7, productId: 22 });
	});

	it('Escape closes the dropdown and binds nothing', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.type(input, 'рельс');
		await waitFor(() => expect(screen.getByRole('listbox')).toBeInTheDocument());

		await user.keyboard('{Escape}');

		await waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument());
		expect(reassignMutateAsync).not.toHaveBeenCalled();
	});

	it('free text with blur (no pick) does not bind', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.type(input, 'что-то своё');
		await user.tab(); // blur

		expect(reassignMutateAsync).not.toHaveBeenCalled();
		// reverts to the canonical name — free text is not persisted (save semantics preserved)
		await waitFor(() => expect((screen.getByRole('combobox') as HTMLInputElement).value).toBe('старое имя'));
	});

	it('ArrowDown moves the highlight while the list is OPEN', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.type(input, 'рельс');
		await waitFor(() => expect(screen.getByRole('listbox')).toBeInTheDocument());

		// First option is active initially; ArrowDown moves to the second, Enter binds it.
		await user.keyboard('{ArrowDown}');
		await user.keyboard('{Enter}');

		expect(reassignMutateAsync).toHaveBeenCalledWith({ quoteItemId: 7, productId: 22 });
	});

	it('when the list is CLOSED, ArrowDown is not swallowed (bubbles to the grid)', async () => {
		const user = userEvent.setup();
		const gridArrow = vi.fn();
		renderWithProviders(
			<div onKeyDown={(event) => { if (event.key === 'ArrowDown') gridArrow(); }}>
				<ProductNameCell item={makeItem()} index={1} onBrowseCandidates={vi.fn()} />
			</div>,
		);
		const input = screen.getByRole('combobox');
		await user.click(input); // focused, list closed (no typing)

		await user.keyboard('{ArrowDown}');

		// The event reached the container handler (grid navigation stays alive on the name column).
		expect(gridArrow).toHaveBeenCalled();
	});

	it('renders the attach-candidates fallback for an unbound line', async () => {
		const user = userEvent.setup();
		const onBrowse = vi.fn();
		renderWithProviders(<ProductNameCell item={makeItem()} index={1} onBrowseCandidates={onBrowse} />);

		await user.click(screen.getByRole('button', { name: /привязать товар/i }));
		expect(onBrowse).toHaveBeenCalledWith(7);
	});
});
