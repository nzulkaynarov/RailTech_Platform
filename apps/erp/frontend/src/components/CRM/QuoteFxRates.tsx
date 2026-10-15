import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import type { Quote } from '@/api/crmApi';
import { useHasCompanyPermission } from '@/hooks/useCapabilities';
import { formatDate, formatDateTime } from '@/lib/formatLocale';
import { formatFxRate, fxSourceLabelKey } from '@/lib/fx';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { QuoteFxOverrideDialog } from './QuoteFxOverrideDialog';

/**
 * «Курс на <дата>: 1 USD = … UZS (источник)» — курсы КП по валютам себестоимости (M1-ERP-08).
 *
 * Строки приходят с сервера (`fx_rates`, только с `quote.view_cost_margin` — иначе блока нет).
 * Черновик живёт по текущему курсу, при отправке на согласование курс фиксируется (`fx_mode`).
 * Финансист (`finance.rates`) задаёт договорной курс с причиной — до отправки клиенту.
 */
export function QuoteFxRates({ quote, className }: { quote: Quote; className?: string }) {
	const { t } = useTranslation();
	const canOverride = useHasCompanyPermission('finance.rates');
	const [dialogCurrency, setDialogCurrency] = useState<string | null>(null);
	const rates = quote.fx_rates ?? [];
	if (rates.length === 0) return null;

	const editable = canOverride && !quote.frozen_at;
	const fixed = quote.fx_mode === 'fixed';
	const fixedAt = quote.fx_fixed_at ?? quote.frozen_at;

	return (
		<div className={cn('flex flex-col gap-2', className)} data-testid="quote-fx-rates">
			<div className="flex flex-wrap items-center justify-between gap-2">
				<span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('quote.fx.title')}</span>
				<Badge variant={fixed ? 'secondary' : 'outline'}>{fixed ? t('quote.fx.modeFixed') : t('quote.fx.modeLive')}</Badge>
			</div>
			{rates.map((row) => (
				<div key={row.currency} className="flex flex-col gap-1 rounded-md border px-2.5 py-2">
					{row.missing ? (
						<p className="flex items-start gap-1.5 text-xs font-medium text-destructive">
							<AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
							{t('quote.fx.missing', { currency: row.currency })}
						</p>
					) : (
						<p className="text-sm tabular-nums">
							{t('quote.fx.line', {
								date: formatDate(row.rate_date),
								currency: row.currency,
								rate: formatFxRate(row.rate),
							})}{' '}
							<span className="text-xs text-muted-foreground">({t(fxSourceLabelKey(row.source))})</span>
						</p>
					)}
					{row.override && (
						<p className="text-xs text-muted-foreground">
							{t('quote.fx.overrideInfo', {
								reason: row.override.reason,
								by: row.override.set_by_name || '—',
								cbu: row.snapshot_rate ? formatFxRate(row.snapshot_rate) : '—',
							})}
						</p>
					)}
					{editable && (
						<Button
							type="button"
							variant="link"
							size="sm"
							className="h-auto w-fit p-0 text-xs"
							onClick={() => setDialogCurrency(row.currency)}
						>
							{row.missing ? t('quote.fx.setRate') : t('quote.fx.changeRate')}
						</Button>
					)}
				</div>
			))}
			<p className="text-xs text-muted-foreground">
				{fixed
					? (fixedAt ? t('quote.fx.fixedHelp', { date: formatDateTime(fixedAt) }) : t('quote.fx.fixedHelpNoDate'))
					: t('quote.fx.liveHelp')}
			</p>
			{dialogCurrency && (
				<QuoteFxOverrideDialog
					quote={quote}
					currency={dialogCurrency}
					open
					onOpenChange={(open) => { if (!open) setDialogCurrency(null); }}
				/>
			)}
		</div>
	);
}
