import Decimal from 'decimal.js';
import type { QuoteCharge } from '@/api/crmApi';
import { toDecimal } from '@/utils/decimal';

/**
 * One resolved step of the КП charge cascade: the charge, the running base it was
 * applied to, its signed amount, and the running tax-exclusive total AFTER it.
 */
export interface CascadeStep {
	id: number;
	/** ChargeType lookup CODE (e.g. "FREIGHT") — the consumer localizes it via
	 *  `chargeTypeLabelKey`; `name` is the raw RU-only DB fallback for unknown codes. */
	chargeType: string;
	name: string;
	description?: string;
	isDeduction: boolean;
	isPercent: boolean;
	ratePercent: string | null;
	base: Decimal;      // running tax-exclusive total BEFORE this charge (the % base)
	signed: Decimal;    // signed amount applied (penny-quantized, − for a deduction)
	runningAfter: Decimal;
}

export interface CascadeResult {
	subtotal: Decimal;
	steps: CascadeStep[];
	chargesTotal: Decimal;
	taxExclusive: Decimal;
	vatAmount: Decimal;
	totalInclVat: Decimal;
}

const PENNY_DP = 2;
const HALF_UP = Decimal.ROUND_HALF_UP; // matches Python's ROUND_HALF_UP (away from zero)
const q2 = (value: Decimal): Decimal => value.toDecimalPlaces(PENNY_DP, HALF_UP);

/**
 * MIRROR of backend `QuoteViewSet.recalculate_quote` + `QuoteCharge.resolve_signed`
 * (crm/services/quotes.py, crm/models/charges.py). Computed on decimal.js with the SAME
 * order of operations and penny-rounding so every intermediate running total, the tax base,
 * VAT and the grand total match the server-stored fields to the копейка:
 *
 *   running = subtotal_excl_vat                     (already penny-quantized on the server)
 *   for each charge (sort_order, id):
 *     base   = running
 *     signed = q2( is_deduction ? −raw : raw )      raw = base·rate% (percent) OR amount (fixed)
 *     running = max(running + signed, 0)            KP-03: base never goes negative
 *   charges_total = q2(running − subtotal)
 *   tax_exclusive = q2(running)
 *   vat_amount    = q2(tax_exclusive · vat_rate/100)
 *   total         = tax_exclusive + vat_amount
 *
 * `charges` must be pre-ordered by (sort_order, id) — the API returns them that way.
 */
export function buildChargeCascade(
	subtotal: string | number | null | undefined,
	charges: QuoteCharge[],
	vatRate: string | number | null | undefined,
): CascadeResult {
	const subtotalDecimal = q2(toDecimal(subtotal));
	let running = subtotalDecimal;
	const steps: CascadeStep[] = [];

	for (const charge of charges) {
		const isPercent = charge.rate_percent !== null && charge.rate_percent !== undefined && charge.rate_percent !== '';
		const base = running;
		// resolve_signed: percent (rate% of the RUNNING base) takes priority over the fixed amount.
		const raw = isPercent
			? base.mul(toDecimal(charge.rate_percent).div(100))
			: toDecimal(charge.amount);
		const signed = q2(charge.is_deduction ? raw.neg() : raw);
		running = Decimal.max(running.plus(signed), new Decimal(0));
		steps.push({
			id: charge.id,
			chargeType: charge.charge_type,
			name: charge.charge_type_name || charge.charge_type,
			description: charge.description,
			isDeduction: charge.is_deduction,
			isPercent,
			ratePercent: isPercent ? String(charge.rate_percent) : null,
			base,
			signed,
			runningAfter: running,
		});
	}

	const chargesTotal = q2(running.minus(subtotalDecimal));
	const taxExclusive = q2(running);
	const vatAmount = q2(taxExclusive.mul(toDecimal(vatRate).div(100)));
	const totalInclVat = taxExclusive.plus(vatAmount);

	return { subtotal: subtotalDecimal, steps, chargesTotal, taxExclusive, vatAmount, totalInclVat };
}
