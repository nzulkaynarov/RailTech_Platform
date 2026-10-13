import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '@/test/renderWithProviders';
import { NumericCell } from '@/components/QuoteBuilder/NumericCell';

/**
 * WP-D / spec §2 P0-5 — the safe numeric input. Decimal comma parses, clearing the
 * field does not commit «0», an empty blur reverts, and out of focus the value is
 * grouped by locale.
 */
describe('NumericCell', () => {
	it('parses a decimal-comma entry «1234,50» and commits 1234.5', async () => {
		const user = userEvent.setup();
		const onCommit = vi.fn();
		renderWithProviders(<NumericCell value="0" onCommit={onCommit} ariaLabel="price" />);

		const input = screen.getByRole('textbox', { name: 'price' });
		await user.click(input);
		await user.clear(input);
		await user.type(input, '1234,50');
		await user.keyboard('{Enter}'); // blur → commit

		expect(onCommit).toHaveBeenCalledTimes(1);
		expect(Number(onCommit.mock.calls[0][0])).toBe(1234.5);
	});

	it('does NOT commit «0» when the field is cleared during editing', async () => {
		const user = userEvent.setup();
		const onCommit = vi.fn();
		renderWithProviders(<NumericCell value="500" onCommit={onCommit} ariaLabel="price" />);

		const input = screen.getByRole('textbox', { name: 'price' });
		await user.click(input);
		await user.clear(input);
		await user.keyboard('{Enter}'); // blur with an empty buffer

		expect(onCommit).not.toHaveBeenCalled();
	});

	it('reverts to the committed value on an empty blur', async () => {
		const user = userEvent.setup();
		const onCommit = vi.fn();
		renderWithProviders(<NumericCell value="500" onCommit={onCommit} ariaLabel="price" />);

		const input = screen.getByRole('textbox', { name: 'price' }) as HTMLInputElement;
		await user.click(input);
		await user.clear(input);
		await user.tab(); // blur away

		// The grouped server value is restored (Node's ru locale groups 500 → "500").
		const expected = new Intl.NumberFormat('ru', { maximumFractionDigits: 2 }).format(500);
		expect(input.value).toBe(expected);
		expect(onCommit).not.toHaveBeenCalled();
	});

	it('renders the value grouped by locale when not focused', () => {
		const onCommit = vi.fn();
		renderWithProviders(<NumericCell value={1234567} onCommit={onCommit} ariaLabel="price" />);

		const input = screen.getByRole('textbox', { name: 'price' }) as HTMLInputElement;
		const grouped = new Intl.NumberFormat('ru', { maximumFractionDigits: 2 }).format(1234567);
		expect(input.value).toBe(grouped);
		// Grouping actually happened (not the raw digit run).
		expect(input.value).not.toBe('1234567');
	});

	it('clamps to max and commits the ceiling', async () => {
		const user = userEvent.setup();
		const onCommit = vi.fn();
		renderWithProviders(
			<NumericCell value="1" onCommit={onCommit} max={100} maxToastKey="quote.validation.qtyTooLarge" ariaLabel="qty" />,
		);

		const input = screen.getByRole('textbox', { name: 'qty' });
		await user.click(input);
		await user.clear(input);
		await user.type(input, '9999');
		await user.keyboard('{Enter}');

		expect(onCommit).toHaveBeenCalledWith('100');
	});
});
