import { type ComponentProps } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';

import { ExcelPasteDialog } from '@/components/QuoteBuilder/ExcelPasteDialog';
import { renderWithProviders } from '@/test/renderWithProviders';

/**
 * Excel-paste preview dialog (spec §5 п.12). Confirms the payload it hands to the parent
 * (which fires ONE bulk-create), and that a rejected batch's per-row codes highlight the
 * offending rows inline WITHOUT closing the dialog so the seller can fix them.
 */
function renderDialog(overrides: Partial<ComponentProps<typeof ExcelPasteDialog>> = {}) {
	const props: ComponentProps<typeof ExcelPasteDialog> = {
		open: true,
		onOpenChange: vi.fn(),
		initialText: 'Болт М12\t100\t2 500,50\nГайка М12\t200\t900',
		maxRows: 500,
		submitting: false,
		rowErrors: {},
		onConfirm: vi.fn(),
		...overrides,
	};
	renderWithProviders(<ExcelPasteDialog {...props} />);
	return props;
}

describe('ExcelPasteDialog', () => {
	it('confirms with the bulk-create payload derived from the pasted table', () => {
		const onConfirm = vi.fn();
		renderDialog({ onConfirm });

		fireEvent.click(screen.getByRole('button', { name: /Добавить позиций/ }));

		expect(onConfirm).toHaveBeenCalledTimes(1);
		expect(onConfirm).toHaveBeenCalledWith([
			{ imported_raw_name: 'Болт М12', quantity: 100, frozen_base_price: '2500.50' },
			{ imported_raw_name: 'Гайка М12', quantity: 200, frozen_base_price: '900' },
		]);
	});

	it('shows the recognized-row count', () => {
		renderDialog();
		expect(screen.getByText('Распознано строк: 2')).toBeInTheDocument();
	});

	it('highlights the offending row from per-row errors and keeps the dialog open', () => {
		const onOpenChange = vi.fn();
		renderDialog({
			onOpenChange,
			rowErrors: { 0: { imported_raw_name: 'QUOTE_ITEM_NAME_REQUIRED' } },
		});

		// Localized code (apiErrors.QUOTE_ITEM_NAME_REQUIRED) is shown on the cell…
		expect(screen.getAllByText('Укажите наименование позиции').length).toBeGreaterThan(0);
		// …and the fix-and-retry banner appears.
		expect(screen.getByText('Исправьте отмеченные строки и повторите.')).toBeInTheDocument();
		// The offending row is marked invalid.
		const invalidRow = document.querySelector('[data-row-index="0"][aria-invalid="true"]');
		expect(invalidRow).not.toBeNull();
		// Rendering errors never auto-closes the dialog.
		expect(onOpenChange).not.toHaveBeenCalledWith(false);
	});

	it('warns and truncates when the paste exceeds the row cap', () => {
		const source = Array.from({ length: 12 }, (_unused, index) => `Позиция ${index}\t1`).join('\n');
		const onConfirm = vi.fn();
		renderDialog({ initialText: source, maxRows: 10, onConfirm });

		// Warning references the cap and the total.
		expect(screen.getByText(/Будут добавлены первые 10 из 12 строк/)).toBeInTheDocument();
		// Confirm sends exactly the capped number of rows.
		fireEvent.click(screen.getByRole('button', { name: /Добавить позиций: 10/ }));
		expect(onConfirm.mock.calls[0][0]).toHaveLength(10);
	});
});
