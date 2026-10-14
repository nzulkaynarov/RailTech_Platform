import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { useUserStore } from '@/store/userStore';
import type { MarginDeviation } from '@/api/financeApi';
import { formatDate, formatNumber } from '@/lib/formatLocale';
import { DealMarginDeviationCard } from '../DealMarginDeviationCard';

const pct = (value: number) => formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const getMarginDeviation = vi.fn();
const recordPurchaseActual = vi.fn();
const removePurchaseActual = vi.fn();
vi.mock('@/api/financeApi', () => ({
	financeApi: {
		getMarginDeviation: (...args: unknown[]) => getMarginDeviation(...args),
		recordPurchaseActual: (...args: unknown[]) => recordPurchaseActual(...args),
		removePurchaseActual: (...args: unknown[]) => removePurchaseActual(...args),
	},
}));

const deviation: MarginDeviation = {
	deal: 5,
	currency: 'UZS',
	reference_quote: { id: 9, version: 2, number: 'КП-2026-00007', status_code: 'SENT', frozen_at: null, fx_fixed_at: null },
	has_actuals: true,
	revenue: '17580000.00',
	quoted_cost: '14650000.00',
	quoted_profit: '2930000.00',
	quoted_margin_percent: '16.67',
	actual_cost: '14900000.00',
	actual_profit: '2680000.00',
	actual_margin_percent: '15.24',
	deviation_amount: '-250000.00',
	deviation_percent_points: '-1.43',
	deviation_profit_percent: '-8.53',
	rows: [
		{
			currency: 'USD',
			lines: 1,
			quoted_amount: '1000.00',
			quoted_rate: '12650',
			quoted_rate_date: '2026-10-14',
			quoted_cost: '12650000.00',
			has_actual: true,
			actual_amount: null,
			actual_rate: '12900',
			actual_cost: '12900000.00',
			cost_deviation: '250000.00',
			purchased_on: '2026-10-14',
			note: 'Счёт поставщика',
			entered_by_name: 'Фин',
			suggested_rate: '12900',
			suggested_rate_date: '2026-10-14',
		},
		{
			currency: 'UZS',
			lines: 2,
			quoted_amount: '2000000.00',
			quoted_rate: '1',
			quoted_rate_date: null,
			quoted_cost: '2000000.00',
			has_actual: false,
			actual_amount: null,
			actual_rate: null,
			actual_cost: '2000000.00',
			cost_deviation: '0.00',
			purchased_on: null,
			note: '',
			entered_by_name: '',
			suggested_rate: '1',
			suggested_rate_date: '2026-10-14',
		},
	],
};

const grant = (...permissions: string[]) =>
	useUserStore.setState({ capabilities: { ...useUserStore.getState().capabilities, permissions } });

describe('DealMarginDeviationCard — отклонение маржи (M1-ERP-08)', () => {
	beforeEach(() => {
		getMarginDeviation.mockReset().mockResolvedValue(deviation);
		recordPurchaseActual.mockReset().mockResolvedValue(deviation);
		removePurchaseActual.mockReset().mockResolvedValue({ ...deviation, has_actuals: false });
	});

	it('без права видеть маржу — ни блока, ни запроса', () => {
		grant('finance.rates');
		const { container } = renderWithProviders(<DealMarginDeviationCard dealId={5} />);
		expect(container).toBeEmptyDOMElement();
		expect(getMarginDeviation).not.toHaveBeenCalled();
	});

	it('показывает маржу по КП и по факту, отклонение и строки валют', async () => {
		grant('quote.view_cost_margin');
		renderWithProviders(<DealMarginDeviationCard dealId={5} />);
		expect(await screen.findByText('Маржа сделки: КП и факт закупки')).toBeInTheDocument();
		expect(screen.getByText(`${pct(16.67)}%`)).toBeInTheDocument();
		expect(screen.getByText(`${pct(15.24)}%`)).toBeInTheDocument();
		expect(screen.getByText(`${pct(-1.43)} п. п.`)).toBeInTheDocument();
		expect(screen.getByTestId('margin-row-USD')).toHaveTextContent(`факт от ${formatDate('2026-10-14')}`);
		expect(screen.getByTestId('margin-row-UZS')).toHaveTextContent('как в КП');
		// Без права вносить факт — кнопок нет.
		expect(screen.queryByRole('button', { name: /Внести факт/ })).not.toBeInTheDocument();
	});

	it('закупщик вносит факт: сумма пусто — как в КП, курс подставлен из справочника', async () => {
		grant('quote.view_cost_margin', 'supply.manage');
		renderWithProviders(<DealMarginDeviationCard dealId={5} />);
		fireEvent.click(await screen.findByRole('button', { name: /Внести факт/ }));
		expect(screen.queryByLabelText(/Фактический курс/)).not.toBeInTheDocument(); // UZS — курс 1
		fireEvent.change(screen.getByLabelText('Фактическая себестоимость, UZS'), { target: { value: '2 100 000' } });
		fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
		await waitFor(() =>
			expect(recordPurchaseActual).toHaveBeenCalledWith(5, {
				currency: 'UZS', amount: '2100000', rate: null, purchased_on: null, note: '',
			}),
		);
	});

	it('финансист правит и удаляет факт по валюте', async () => {
		grant('quote.view_cost_margin', 'finance.rates');
		renderWithProviders(<DealMarginDeviationCard dealId={5} />);
		fireEvent.click(await screen.findByRole('button', { name: /Изменить/ }));
		expect(screen.getByLabelText('Фактический курс: сум за 1 USD')).toHaveValue('12900');
		fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
		fireEvent.click(screen.getByRole('button', { name: 'Удалить факт закупки USD' }));
		await waitFor(() => expect(removePurchaseActual).toHaveBeenCalledWith(5, 'USD'));
	});
});
