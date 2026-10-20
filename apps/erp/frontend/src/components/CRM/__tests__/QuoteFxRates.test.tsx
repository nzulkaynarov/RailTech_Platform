import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { useUserStore } from '@/store/userStore';
import type { Quote, QuoteFxRate } from '@/api/crmApi';
import { formatDate } from '@/lib/formatLocale';
import { formatFxRate } from '@/lib/fx';
import { QuoteFxRates } from '../QuoteFxRates';

const setQuoteFxOverride = vi.fn();
vi.mock('@/api/crmApi', async (importOriginal) => {
	const actual = await importOriginal<typeof import('@/api/crmApi')>();
	return { ...actual, crmApi: { ...actual.crmApi, setQuoteFxOverride: (...args: unknown[]) => setQuoteFxOverride(...args) } };
});

const usd: QuoteFxRate = {
	currency: 'USD',
	rate: '12650.5',
	rate_date: '2026-10-14',
	source: 'CBU',
	snapshot_rate: '12650.5',
	snapshot_rate_date: '2026-10-14',
	snapshot_source: 'CBU',
	override: null,
	missing: false,
};

const quote = (patch: Partial<Quote> = {}): Quote => ({
	id: 7,
	deal: 1,
	version: 1,
	status: 1,
	status_code: 'DRAFT',
	status_name: 'Черновик',
	items: [],
	subtotal_excl_vat: '0',
	vat_amount: '0',
	total_incl_vat: '0',
	fx_rates: [usd],
	fx_mode: 'live',
	fx_fixed_at: null,
	frozen_at: null,
	...patch,
} as Quote);

const grant = (...permissions: string[]) =>
	useUserStore.setState({ capabilities: { ...useUserStore.getState().capabilities, permissions } });

describe('QuoteFxRates — курс на дату КП (M1-ERP-08)', () => {
	beforeEach(() => {
		setQuoteFxOverride.mockReset();
		grant();
	});

	it('показывает «Курс на <дата>: 1 USD = … UZS (источник)» и режим черновика', () => {
		renderWithProviders(<QuoteFxRates quote={quote()} />);
		expect(screen.getByText(`Курс на ${formatDate("2026-10-14")}: 1 USD = ${formatFxRate("12650.5")} UZS`, { exact: false })).toBeInTheDocument();
		expect(screen.getByText('(ЦБ РУз)')).toBeInTheDocument();
		expect(screen.getByText('Черновик: курс на сегодня')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Изменить курс' })).not.toBeInTheDocument();
	});

	it('ничего не рисует без курсов (нет права видеть себестоимость — сервер не отдаёт fx_rates)', () => {
		const { container } = renderWithProviders(<QuoteFxRates quote={quote({ fx_rates: undefined })} />);
		expect(container).toBeEmptyDOMElement();
	});

	it('нет курса — предупреждение и «Задать курс» для финансиста', () => {
		grant('finance.rates');
		const missing = { ...usd, rate: null, rate_date: null, source: null, snapshot_rate: null, missing: true };
		renderWithProviders(<QuoteFxRates quote={quote({ fx_rates: [missing] })} />);
		expect(screen.getByText(/Нет курса USD на дату КП/)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Задать курс' })).toBeInTheDocument();
	});

	it('договорной курс показывает причину и курс ЦБ; на отправленном КП менять нельзя', () => {
		grant('finance.rates');
		const override = {
			...usd,
			rate: '12800',
			source: 'OVERRIDE',
			override: { rate: '12800', reason: 'По договору', set_by_name: 'Фин Финов', set_at: '2026-10-14T10:00:00+05:00' },
		};
		renderWithProviders(
			<QuoteFxRates
				quote={quote({ fx_rates: [override], fx_mode: 'fixed', fx_fixed_at: '2026-10-14T10:00:00+05:00', frozen_at: '2026-10-14T11:00:00+05:00' })}
			/>,
		);
		expect(screen.getByText(/Договорной курс: По договору · Фин Финов/)).toBeInTheDocument();
		expect(screen.getByText('(договорной курс)')).toBeInTheDocument();
		expect(screen.getByText('Курс зафиксирован')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Изменить курс' })).not.toBeInTheDocument();
	});

	it.each(['PENDING_APPROVAL', 'READY_TO_SEND', 'PENDING_TRADE_REVIEW'])(
		'на статусе %s курс менять нельзя — подсказка про возврат в черновик',
		(statusCode) => {
			grant('finance.rates');
			renderWithProviders(<QuoteFxRates quote={quote({ status_code: statusCode })} />);
			expect(screen.queryByRole('button', { name: 'Изменить курс' })).not.toBeInTheDocument();
			expect(screen.getByText(/Договорной курс меняется только в черновике/)).toBeInTheDocument();
		},
	);

	it('финансист задаёт курс с причиной — без причины кнопка неактивна', async () => {
		grant('finance.rates');
		setQuoteFxOverride.mockResolvedValue(quote());
		renderWithProviders(<QuoteFxRates quote={quote()} />);

		fireEvent.click(screen.getByRole('button', { name: 'Изменить курс' }));
		fireEvent.change(screen.getByLabelText('Сколько сум за 1 USD'), { target: { value: '12800,5' } });
		const save = screen.getByRole('button', { name: 'Сохранить курс' });
		expect(save).toBeDisabled();
		fireEvent.change(screen.getByLabelText('Причина'), { target: { value: 'Курс по договору' } });
		expect(save).toBeEnabled();
		fireEvent.click(save);

		await waitFor(() =>
			expect(setQuoteFxOverride).toHaveBeenCalledWith(7, { currency: 'USD', rate: '12800.5', reason: 'Курс по договору' }),
		);
	});

	it('неверный курс подсвечивается и не отправляется', () => {
		grant('finance.rates');
		renderWithProviders(<QuoteFxRates quote={quote()} />);
		fireEvent.click(screen.getByRole('button', { name: 'Изменить курс' }));
		fireEvent.change(screen.getByLabelText('Сколько сум за 1 USD'), { target: { value: '0' } });
		fireEvent.change(screen.getByLabelText('Причина'), { target: { value: 'x' } });
		expect(screen.getByText('Курс — положительное число, до 6 знаков после запятой')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Сохранить курс' })).toBeDisabled();
	});
});
