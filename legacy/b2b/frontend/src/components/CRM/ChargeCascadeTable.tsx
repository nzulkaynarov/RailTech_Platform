import React from 'react';
import { useTranslation } from 'react-i18next';
import Decimal from 'decimal.js';
import type { QuoteCharge, QuoteEconomics } from '@/api/crmApi';
import { toDecimal, formatMoney } from '@/utils/decimal';
import { buildChargeCascade } from '@/utils/chargeCascade';
import { chargeTypeLabelKey } from '@/lib/codes';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

/** Signed money label with an explicit +/− prefix (− is the U+2212 minus, like the CRUD rows). */
const signedLabel = (value: Decimal, currency?: string): string => {
	const sign = value.isNegative() ? '−' : '+';
	return `${sign}${formatMoney(value.abs().toString(), currency)}`;
};

interface ChargeCascadeTableProps {
	subtotal: string | number | null | undefined;
	charges: QuoteCharge[];
	vatRate?: string | number | null;
	currency?: string;
	/**
	 * Seller unit economics — present ONLY for a viewer entitled to see cost/margin.
	 * null/undefined ⇒ cost-redacted: the cascade still renders (presentation SELL prices
	 * are safe), but the margin badge is withheld so cost/margin never leaks.
	 */
	economics?: QuoteEconomics | null;
}

/**
 * Transparent step-by-step КП price cascade: how the line subtotal becomes the final
 * VAT-inclusive total through the ordered charges/discounts. Read top→bottom; every row
 * shows both the delta and the running total after it. Presentation prices only — safe for
 * buyers and cost-redacted viewers; the "below min. margin" badge shows only with economics.
 */
export const ChargeCascadeTable: React.FC<ChargeCascadeTableProps> = ({
	subtotal, charges, vatRate, currency, economics,
}) => {
	const { t } = useTranslation();
	const cascade = buildChargeCascade(subtotal, charges, vatRate);
	const vatPercentLabel = toDecimal(vatRate).toDecimalPlaces(2, Decimal.ROUND_HALF_UP).toNumber();
	const showBelowFloor = !!economics && economics.below_floor;

	return (
		<div className="flex flex-col gap-1">
			<h4 className="text-xs font-semibold text-muted-foreground">{t('quote.charges.cascade.title')}</h4>
			<div className="flex flex-col rounded-md border tabular-nums">
				{/* Subtotal (lines) */}
				<div className="flex items-center justify-between gap-2 px-3 py-1.5">
					<span className="text-sm text-muted-foreground">{t('quote.charges.cascade.subtotal')}</span>
					<span className="font-mono text-sm">{formatMoney(cascade.subtotal.toString(), currency)}</span>
				</div>

				{/* One row per charge, in cascade order */}
				{cascade.steps.map((step) => (
					<div key={step.id} className="flex items-center justify-between gap-3 border-t px-3 py-1.5">
						<div className="flex min-w-0 items-center gap-2">
							<Badge variant={step.isDeduction ? 'secondary' : 'outline'} className="shrink-0">
								{step.isDeduction ? t('quote.charges.discount') : t('quote.charges.charge')}
							</Badge>
							<span className="truncate text-sm font-medium">
								{chargeTypeLabelKey(step.chargeType) ? t(chargeTypeLabelKey(step.chargeType)) : step.name}
							</span>
							{step.isPercent && (
								<span className="hidden text-xs text-muted-foreground sm:inline">
									{t('quote.charges.ofBase', { rate: step.ratePercent, base: formatMoney(step.base.toString(), currency) })}
								</span>
							)}
							{step.description && (
								<span className="hidden truncate text-xs text-muted-foreground md:inline">— {step.description}</span>
							)}
						</div>
						<div className="flex shrink-0 items-center gap-3">
							<span className={cn('font-mono text-xs', step.isDeduction ? 'text-destructive' : 'text-muted-foreground')}>
								{signedLabel(step.signed, currency)}
							</span>
							<span className="w-32 text-right font-mono text-sm">
								{formatMoney(step.runningAfter.toString(), currency)}
							</span>
						</div>
					</div>
				))}

				{/* Tax base = running total after all charges */}
				<div className="flex items-center justify-between gap-2 border-t px-3 py-1.5">
					<span className="text-sm text-muted-foreground">{t('quote.charges.cascade.taxBase')}</span>
					<span className="font-mono text-sm font-medium">{formatMoney(cascade.taxExclusive.toString(), currency)}</span>
				</div>

				{/* + VAT */}
				<div className="flex items-center justify-between gap-2 border-t px-3 py-1.5">
					<span className="text-sm text-muted-foreground">
						{t('quote.charges.cascade.vat', { rate: vatPercentLabel })}
					</span>
					<span className="font-mono text-sm">+{formatMoney(cascade.vatAmount.toString(), currency)}</span>
				</div>

				{/* = Grand total (+ optional below-floor margin badge, cost-viewer only) */}
				<div className="flex items-center justify-between gap-2 border-t bg-muted/30 px-3 py-1.5">
					<div className="flex min-w-0 items-center gap-2">
						<span className="text-sm font-semibold">{t('quote.charges.cascade.total')}</span>
						{showBelowFloor && (
							<Badge
								variant="outline"
								className="border-warning/40 bg-warning/10 text-warning"
								title={t('quote.economics.belowFloor', { floor: Number(economics?.min_margin_percent).toFixed(0) })}
							>
								{t('quote.charges.cascade.belowFloor')}
							</Badge>
						)}
					</div>
					<span className="font-mono text-sm font-semibold">{formatMoney(cascade.totalInclVat.toString(), currency)}</span>
				</div>
			</div>
		</div>
	);
};
