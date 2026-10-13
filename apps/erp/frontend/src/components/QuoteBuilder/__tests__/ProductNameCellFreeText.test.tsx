import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import { TooltipProvider } from '@/components/ui/tooltip';
import type { QuoteItem } from '@/api/crmApi';
import type { Product } from '@/api/catalogApi';

/**
 * U3 — a free-typed ITEM name must PERSIST.
 *
 * Before this wave, typing a name without picking from the typeahead reverted on blur, so a КП
 * could not carry a line that is not a catalog product. The typed text now commits to the line's
 * own `imported_raw_name` through the single-item PATCH (`onCommitFreeText`).
 *
 * Pinned here: the commit fires on blur, Escape abandons it, a catalog pick does NOT double-write,
 * a blank/unchanged value is never persisted, and a line already BOUND to a catalog product does
 * not write a name it would never display (its name comes from `product.name`, grid AND PDF).
 */

const reassignMutateAsync = vi.fn().mockResolvedValue({});

const PRODUCTS: Product[] = [
	{
		id: 22, name: 'Рельс Р50', description: '', sku: 'R50', status: 1, status_name: 'Опубликован',
		domain_type: 1, domain_type_name: 'Оборудование', base_price: '0', gost_drawing: 'ГОСТ 7174',
		manufacturer_part_number: 'MPN-50',
	} as Product,
];

vi.mock('@/hooks/useDebouncedValue', () => ({ useDebouncedValue: (value: string) => value }));

vi.mock('@/hooks/useCatalog', () => ({
	useProductSearch: (term: string) => ({
		data: term.trim().length >= 2 ? PRODUCTS : [],
		isFetching: false,
	}),
}));

vi.mock('@/hooks/useCRM', () => ({
	useReassignProduct: () => ({ mutateAsync: reassignMutateAsync, isPending: false }),
}));

vi.mock('sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

import { ProductNameCell } from '@/components/QuoteBuilder/ProductNameCell';

function makeItem(overrides: Partial<QuoteItem> = {}): QuoteItem {
	return {
		id: 7, quote: 100, product: null, imported_raw_name: 'старое имя', quantity: 1,
		frozen_base_price: '0', frozen_currency: 'UZS', logistics_cost: '0', customs_duty: '0',
		margin_percent: '0', discount_percent: '0', lead_time_days: 0,
		landed_cost: '0', final_price_excl_vat: '0',
		...overrides,
	} as QuoteItem;
}

let commitFreeText: Mock<(itemId: number, value: string) => void>;

function renderCell(item: QuoteItem) {
	// A bound line renders a Tooltip (the «привязано к каталогу» link icon), which needs a provider.
	return renderWithProviders(
		<TooltipProvider>
			<ProductNameCell
				item={item}
				index={1}
				onBrowseCandidates={vi.fn()}
				onCommitFreeText={commitFreeText}
			/>
		</TooltipProvider>,
	);
}

beforeEach(() => {
	vi.clearAllMocks();
	commitFreeText = vi.fn<(itemId: number, value: string) => void>();
});

describe('ProductNameCell — free-typed name persists (U3)', () => {
	it('commits the typed name on blur when nothing was picked from the catalog', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.clear(input);
		await user.type(input, 'Нестандартная деталь по чертежу');
		await user.tab(); // blur

		await waitFor(() => expect(commitFreeText).toHaveBeenCalledTimes(1));
		expect(commitFreeText).toHaveBeenCalledWith(7, 'Нестандартная деталь по чертежу');
		// It is a NAME edit, not a catalog bind — the reassign mutation stays untouched.
		expect(reassignMutateAsync).not.toHaveBeenCalled();
	});

	it('trims the committed value', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.clear(input);
		await user.type(input, '   Втулка   ');
		await user.tab();

		await waitFor(() => expect(commitFreeText).toHaveBeenCalledWith(7, 'Втулка'));
	});

	it('Escape abandons the edit — nothing is persisted', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.clear(input);
		await user.type(input, 'передумал');
		await user.keyboard('{Escape}');

		expect(commitFreeText).not.toHaveBeenCalled();
		// The field is back on the canonical name.
		await waitFor(() => expect((screen.getByRole('combobox') as HTMLInputElement).value).toBe('старое имя'));
	});

	it('picking a catalog suggestion binds the product WITHOUT also writing the typed text', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.clear(input);
		await user.type(input, 'рельс');
		await waitFor(() => expect(screen.getByText('Рельс Р50')).toBeInTheDocument());
		await user.click(screen.getByText('Рельс Р50'));
		await user.tab(); // the blur that follows the pick must not re-commit the draft

		expect(reassignMutateAsync).toHaveBeenCalledWith({ quoteItemId: 7, productId: 22 });
		expect(commitFreeText).not.toHaveBeenCalled();
	});

	it('never persists a blank name', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.clear(input);
		await user.tab();

		expect(commitFreeText).not.toHaveBeenCalled();
	});

	it('does not fire when the text is unchanged (a mere focus/blur is not an edit)', async () => {
		const user = userEvent.setup();
		renderCell(makeItem());

		await user.click(screen.getByRole('combobox'));
		await user.tab();

		expect(commitFreeText).not.toHaveBeenCalled();
	});

	it('a line BOUND to a catalog product does not write a name it would never display', async () => {
		// Its displayed name resolves from `product.name` in the grid AND in the КП PDF, so writing
		// imported_raw_name here would persist an invisible value. The field reverts instead.
		const user = userEvent.setup();
		renderCell(makeItem({ product: 22, product_name: 'Рельс Р50' }));
		const input = screen.getByRole('combobox');

		await user.click(input);
		await user.clear(input);
		await user.type(input, 'моё название');
		await user.tab();

		expect(commitFreeText).not.toHaveBeenCalled();
		await waitFor(() => expect((screen.getByRole('combobox') as HTMLInputElement).value).toBe('Рельс Р50'));
	});
});
