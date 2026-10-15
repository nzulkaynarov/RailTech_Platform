import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import type { MarginDeviation, MarginDeviationRow } from '@/api/financeApi';
import { useMarginDeviation, useRemovePurchaseActual } from '@/hooks/useFinance';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { translateApiError } from '@/lib/apiError';
import { formatFxRate } from '@/lib/fx';
import { formatDate, formatNumber } from '@/lib/formatLocale';
import { cn } from '@/lib/utils';
import { formatMoney, toDecimal } from '@/utils/decimal';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PurchaseActualDialog } from './PurchaseActualDialog';

/** Тон отклонения: меньше прибыли — destructive, больше — success, ноль — обычный текст. */
function toneOf(value: string | null | undefined, invert = false): string {
	const amount = toDecimal(value);
	if (amount.isZero()) return 'text-foreground';
	return amount.isNegative() !== invert ? 'text-destructive' : 'text-success';
}

function signed(value: string | null | undefined, format: (v: string) => string): string {
	const amount = toDecimal(value);
	return `${amount.gt(0) ? '+' : ''}${format(amount.toString())}`;
}

const percent = (value: string | null | undefined) =>
	`${formatNumber(toDecimal(value).toNumber(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;

function Stat({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: string }) {
	return (
		<div className="flex flex-col gap-0.5 rounded-md border p-3">
			<span className="text-xs text-muted-foreground">{label}</span>
			<span className={cn('text-lg font-semibold tabular-nums', tone)}>{value}</span>
			<span className="text-xs tabular-nums text-muted-foreground">{sub}</span>
		</div>
	);
}

function CostCell({ label, amount, currency, rate, cost }: {
	label: string; amount: string | null; currency: string; rate: string | null; cost: string;
}) {
	return (
		<div className="flex flex-col gap-0.5">
			<span className="text-xs text-muted-foreground">{label}</span>
			<span className="text-sm font-medium tabular-nums">{formatMoney(cost, 'UZS')}</span>
			{currency !== 'UZS' && amount !== null && (
				<span className="text-xs tabular-nums text-muted-foreground">
					{formatMoney(amount, currency)} × {formatFxRate(rate)}
				</span>
			)}
		</div>
	);
}

function DeviationRow({ row, canRecord, onEdit, onRemove, removing }: {
	row: MarginDeviationRow; canRecord: boolean; onEdit: () => void; onRemove: () => void; removing: boolean;
}) {
	const { t } = useTranslation();
	return (
		<div className="flex flex-col gap-3 rounded-md border p-3" data-testid={`margin-row-${row.currency}`}>
			<div className="flex flex-wrap items-center justify-between gap-2">
				<div className="flex items-center gap-2">
					<span className="font-mono text-sm font-semibold">{row.currency}</span>
					<span className="text-xs text-muted-foreground">{t('dealMargin.lines', { count: row.lines })}</span>
					{row.has_actual
						? <Badge variant="secondary">{t('dealMargin.actualEntered', { date: formatDate(row.purchased_on) })}</Badge>
						: <Badge variant="outline">{t('dealMargin.asQuoted')}</Badge>}
				</div>
				{canRecord && (
					<div className="flex gap-1">
						<Button type="button" variant="outline" size="sm" onClick={onEdit}>
							{row.has_actual ? <Pencil className="size-3.5" /> : <Plus className="size-3.5" />}
							{row.has_actual ? t('dealMargin.edit') : t('dealMargin.enterActual')}
						</Button>
						{row.has_actual && (
							<Button
								type="button"
								variant="ghost"
								size="icon-sm"
								aria-label={t('dealMargin.remove', { currency: row.currency })}
								onClick={onRemove}
								disabled={removing}
							>
								<Trash2 className="size-3.5" />
							</Button>
						)}
					</div>
				)}
			</div>
			<div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
				<CostCell
					label={t('dealMargin.quotedCost')}
					amount={row.quoted_amount}
					currency={row.currency}
					rate={row.quoted_rate}
					cost={row.quoted_cost}
				/>
				<CostCell
					label={t('dealMargin.actualCost')}
					amount={row.actual_amount ?? row.quoted_amount}
					currency={row.currency}
					rate={row.actual_rate ?? row.quoted_rate}
					cost={row.actual_cost}
				/>
				<div className="flex flex-col gap-0.5">
					<span className="text-xs text-muted-foreground">{t('dealMargin.costDeviation')}</span>
					<span className={cn('text-sm font-medium tabular-nums', toneOf(row.cost_deviation, true))}>
						{signed(row.cost_deviation, (v) => formatMoney(v, 'UZS'))}
					</span>
				</div>
			</div>
			{row.note && <p className="text-xs text-muted-foreground">{row.note}</p>}
		</div>
	);
}

function Summary({ data }: { data: MarginDeviation }) {
	const { t } = useTranslation();
	return (
		<div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
			<Stat
				label={t('dealMargin.quoted')}
				value={percent(data.quoted_margin_percent)}
				sub={t('dealMargin.profit', { amount: formatMoney(data.quoted_profit, 'UZS') })}
			/>
			<Stat
				label={t('dealMargin.actual')}
				value={percent(data.actual_margin_percent)}
				sub={t('dealMargin.profit', { amount: formatMoney(data.actual_profit, 'UZS') })}
			/>
			<Stat
				label={t('dealMargin.deviation')}
				value={signed(data.deviation_amount, (v) => formatMoney(v, 'UZS'))}
				sub={t('dealMargin.points', { points: signed(data.deviation_percent_points, (v) => formatNumber(Number(v), { minimumFractionDigits: 2, maximumFractionDigits: 2 })) })}
				tone={toneOf(data.deviation_amount)}
			/>
		</div>
	);
}

/**
 * «Маржа сделки: КП и факт закупки» (M1-ERP-08) в карточке сделки. Только с `quote.view_cost_margin`;
 * факт закупки вносят `finance.rates` или `supply.manage`. Пока КП не отправлено — блока нет.
 * Цена клиенту не пересчитывается: меняется только маржа сделки.
 */
export function DealMarginDeviationCard({ dealId }: { dealId: number }) {
	const { t } = useTranslation();
	const canView = useHasCompanyPermission('quote.view_cost_margin');
	const canRecordFinance = useHasCompanyPermission('finance.rates');
	const canRecordSupply = useHasCompanyPermission('supply.manage');
	const canRecord = canRecordFinance || canRecordSupply;
	const { data } = useMarginDeviation(dealId, canView);
	const remove = useRemovePurchaseActual(dealId);
	const [editing, setEditing] = useState<MarginDeviationRow | null>(null);

	if (!canView || !data?.reference_quote) return null;
	const reference = data.reference_quote;

	const handleRemove = async (currency: string) => {
		try {
			await remove.mutateAsync(currency);
			toast.success(t('dealMargin.removed'));
		} catch (error) {
			toast.error(translateApiError(error));
		}
	};

	return (
		<Card data-testid="deal-margin-deviation">
			<CardHeader className="pb-2">
				<CardTitle className="text-sm">{t('dealMargin.title')}</CardTitle>
				<CardDescription>
					{t('dealMargin.description', { version: reference.version, number: reference.number || '—' })}
				</CardDescription>
			</CardHeader>
			<CardContent className="flex flex-col gap-4">
				<Summary data={data} />
				{!data.has_actuals && <p className="text-xs text-muted-foreground">{t('dealMargin.noActuals')}</p>}
				<div className="flex flex-col gap-3">
					{data.rows.map((row) => (
						<DeviationRow
							key={row.currency}
							row={row}
							canRecord={canRecord}
							onEdit={() => setEditing(row)}
							onRemove={() => void handleRemove(row.currency)}
							removing={remove.isPending}
						/>
					))}
				</div>
				<p className="text-xs text-muted-foreground">{t('dealMargin.footnote')}</p>
			</CardContent>
			{editing && (
				<PurchaseActualDialog
					dealId={dealId}
					row={editing}
					onOpenChange={(open) => { if (!open) setEditing(null); }}
				/>
			)}
		</Card>
	);
}
