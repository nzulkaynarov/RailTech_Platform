import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';

import { renderWithProviders } from '@/test/renderWithProviders';
import { StickyTotalsBar } from '@/components/QuoteBuilder/StickyTotalsBar';

/**
 * WP-C — the always-visible КП footer. Two display guarantees:
 *  1. It renders the positions count + total incl. VAT, and the Save action, on every viewport.
 *  2. Margin is cost-redaction gated: hidden entirely for a member without quote.view_cost_margin
 *     (canViewCost === false), shown otherwise.
 */
describe('StickyTotalsBar', () => {
	const baseProps = {
		positionsCount: 4,
		totalInclVat: '134.40',
		currency: 'UZS',
		hasUnsavedChanges: false,
		saving: false,
		onSave: vi.fn(),
	};

	it('shows the positions count, the total and a Save action', () => {
		renderWithProviders(<StickyTotalsBar {...baseProps} canViewCost marginPercent={30} />);

		expect(screen.getByText('Позиций: 4')).toBeInTheDocument();
		// The total figure is rendered (formatMoney of 134.40 keeps the integer part «134»).
		expect(screen.getByText(/134/)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Сохранить' })).toBeInTheDocument();
	});

	it('renders the gross margin when the viewer may see cost', () => {
		renderWithProviders(<StickyTotalsBar {...baseProps} canViewCost marginPercent={30} />);

		expect(screen.getByText('Маржа')).toBeInTheDocument();
		expect(screen.getByText('30.0%')).toBeInTheDocument();
	});

	it('hides the margin entirely for a viewer without cost access', () => {
		renderWithProviders(<StickyTotalsBar {...baseProps} canViewCost={false} marginPercent={undefined} />);

		expect(screen.queryByText('Маржа')).toBeNull();
		expect(screen.queryByText(/%$/)).toBeNull();
		// The client-facing total is never gated.
		expect(screen.getByText(/134/)).toBeInTheDocument();
	});

	it('surfaces the unsaved-changes indicator and fires onSave', () => {
		const onSave = vi.fn();
		renderWithProviders(
			<StickyTotalsBar {...baseProps} onSave={onSave} hasUnsavedChanges canViewCost marginPercent={30} />,
		);

		expect(screen.getByText('Есть несохранённые изменения')).toBeInTheDocument();
		fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
		expect(onSave).toHaveBeenCalledOnce();
	});
});
