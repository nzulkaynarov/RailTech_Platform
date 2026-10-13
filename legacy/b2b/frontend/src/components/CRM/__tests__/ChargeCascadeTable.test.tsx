import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { QuoteCharge, QuoteEconomics } from '@/api/crmApi';
import { ChargeCascadeTable } from '../ChargeCascadeTable';
import { buildChargeCascade } from '@/utils/chargeCascade';

/** Minimal QuoteCharge factory — only the fields the cascade reads. */
const charge = (over: Partial<QuoteCharge> & Pick<QuoteCharge, 'id'>): QuoteCharge => ({
	quote: 1,
	charge_type: over.charge_type ?? 'FREIGHT',
	amount: '0',
	is_deduction: false,
	...over,
});

const economics = (over: Partial<QuoteEconomics> = {}): QuoteEconomics => ({
	total_landed_cost: '800.00',
	gross_profit: '200.00',
	gross_margin_percent: '20.0',
	markup_percent: '25.0',
	charge_cost_total: '0.00',
	operating_profit: '200.00',
	below_cost: false,
	below_floor: false,
	min_margin_percent: '15',
	target_margin_percent: '25',
	fx_missing: [],
	...over,
});

describe('buildChargeCascade — mirror of recalculate_quote', () => {
	it('cascades percent + amount, addition + deduction with correct running totals', () => {
		// subtotal 1000.00, VAT 12%
		//  1) FREIGHT  +10%  of 1000.00 → +100.00 → running 1100.00
		//  2) DISCOUNT − 5%  of 1100.00 → − 55.00 → running 1045.00 (base is the RUNNING total)
		//  3) INSURANCE +30.00 fixed    → + 30.00 → running 1075.00
		const charges: QuoteCharge[] = [
			charge({ id: 1, charge_type: 'FREIGHT', rate_percent: '10.00', is_deduction: false }),
			charge({ id: 2, charge_type: 'DISCOUNT', rate_percent: '5.00', is_deduction: true }),
			charge({ id: 3, charge_type: 'INSURANCE', amount: '30.00', rate_percent: null, is_deduction: false }),
		];
		const result = buildChargeCascade('1000.00', charges, '12');

		expect(result.subtotal.toFixed(2)).toBe('1000.00');
		// Per-step base (the % base) and running total after each charge.
		expect(result.steps[0].base.toFixed(2)).toBe('1000.00');
		expect(result.steps[0].signed.toFixed(2)).toBe('100.00');
		expect(result.steps[0].runningAfter.toFixed(2)).toBe('1100.00');

		expect(result.steps[1].base.toFixed(2)).toBe('1100.00');
		expect(result.steps[1].signed.toFixed(2)).toBe('-55.00');
		expect(result.steps[1].runningAfter.toFixed(2)).toBe('1045.00');

		expect(result.steps[2].base.toFixed(2)).toBe('1045.00');
		expect(result.steps[2].signed.toFixed(2)).toBe('30.00');
		expect(result.steps[2].runningAfter.toFixed(2)).toBe('1075.00');

		// Aggregates match the server-stored fields.
		expect(result.chargesTotal.toFixed(2)).toBe('75.00');
		expect(result.taxExclusive.toFixed(2)).toBe('1075.00');
		expect(result.vatAmount.toFixed(2)).toBe('129.00'); // 1075.00 × 12%
		expect(result.totalInclVat.toFixed(2)).toBe('1204.00');
	});

	it('rounds each signed charge HALF_UP (away from zero) at 2 dp', () => {
		// 100.05 × 10% = 10.005 → HALF_UP → 10.01 → running 110.06
		const result = buildChargeCascade('100.05', [charge({ id: 1, rate_percent: '10.00' })], '0');
		expect(result.steps[0].signed.toFixed(2)).toBe('10.01');
		expect(result.taxExclusive.toFixed(2)).toBe('110.06');
	});

	it('clamps the running base at zero (no negative tax base)', () => {
		// A 200 discount on a 100 subtotal → running max(−100, 0) = 0.00
		const result = buildChargeCascade('100.00', [charge({ id: 1, amount: '200.00', is_deduction: true })], '12');
		expect(result.steps[0].runningAfter.toFixed(2)).toBe('0.00');
		expect(result.taxExclusive.toFixed(2)).toBe('0.00');
		expect(result.vatAmount.toFixed(2)).toBe('0.00');
		expect(result.totalInclVat.toFixed(2)).toBe('0.00');
	});

	it('with no charges: subtotal → +VAT → total', () => {
		const result = buildChargeCascade('500.00', [], '12');
		expect(result.steps).toHaveLength(0);
		expect(result.chargesTotal.toFixed(2)).toBe('0.00');
		expect(result.taxExclusive.toFixed(2)).toBe('500.00');
		expect(result.vatAmount.toFixed(2)).toBe('60.00');
		expect(result.totalInclVat.toFixed(2)).toBe('560.00');
	});
});

describe('ChargeCascadeTable — rendering & cost redaction', () => {
	const charges: QuoteCharge[] = [
		charge({ id: 1, charge_type: 'FREIGHT', charge_type_name: 'Фрахт', rate_percent: '10.00' }),
	];

	it('renders the cascade rows (subtotal, tax base, total)', () => {
		renderWithProviders(
			<ChargeCascadeTable subtotal="1000.00" charges={charges} vatRate="12" currency="UZS" economics={null} />,
		);
		expect(screen.getByText('Каскад расчёта')).toBeInTheDocument();
		expect(screen.getByText('Подытог (позиции)')).toBeInTheDocument();
		expect(screen.getByText('Налоговая база')).toBeInTheDocument();
		expect(screen.getByText('Итого с НДС')).toBeInTheDocument();
	});

	it('shows the "below min. margin" badge only for a cost-viewer whose margin is below floor', () => {
		renderWithProviders(
			<ChargeCascadeTable subtotal="1000.00" charges={charges} vatRate="12" economics={economics({ below_floor: true })} />,
		);
		expect(screen.getByText('ниже мин. маржи')).toBeInTheDocument();
	});

	it('withholds the margin badge when the viewer cannot see cost (economics null)', () => {
		renderWithProviders(
			<ChargeCascadeTable subtotal="1000.00" charges={charges} vatRate="12" economics={null} />,
		);
		expect(screen.queryByText('ниже мин. маржи')).not.toBeInTheDocument();
	});

	it('withholds the margin badge when margin is at/above floor', () => {
		renderWithProviders(
			<ChargeCascadeTable subtotal="1000.00" charges={charges} vatRate="12" economics={economics({ below_floor: false })} />,
		);
		expect(screen.queryByText('ниже мин. маржи')).not.toBeInTheDocument();
	});
});
