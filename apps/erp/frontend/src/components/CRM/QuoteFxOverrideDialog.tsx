import { FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import type { Quote } from '@/api/crmApi';
import { useSetQuoteFxOverride } from '@/hooks/useCRM';
import { translateApiError } from '@/lib/apiError';
import { toDecimal } from '@/utils/decimal';
import { formatFxRate, fxSourceLabelKey } from '@/lib/fx';
import { formatDate } from '@/lib/formatLocale';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

interface QuoteFxOverrideDialogProps {
	quote: Quote;
	currency: string;
	open: boolean;
	onOpenChange: (open: boolean) => void;
}

const REASON_MAX = 500;
// Курс — до 6 знаков после запятой (как справочник курсов на сервере).
const RATE_PATTERN = /^\d{1,12}(\.\d{1,6})?$/;

/**
 * Договорной курс КП (M1-ERP-08): финансист (`finance.rates`) задаёт курс валюты себестоимости
 * вместо курса ЦБ — с обязательной причиной (в журнал КП) — или возвращает курс ЦБ.
 * Монтируется только открытым: форма инициализируется из КП при каждом открытии.
 */
export function QuoteFxOverrideDialog({ quote, currency, open, onOpenChange }: QuoteFxOverrideDialogProps) {
	const { t } = useTranslation();
	const mutation = useSetQuoteFxOverride();
	const row = quote.fx_rates?.find((r) => r.currency === currency);
	const [rate, setRate] = useState(row?.override?.rate ?? '');
	const [reason, setReason] = useState('');

	const normalizedRate = rate.trim().replace(',', '.');
	const rateValid = RATE_PATTERN.test(normalizedRate) && toDecimal(normalizedRate).gt(0);
	const reasonValid = reason.trim().length > 0;

	async function save(nextRate: string | null) {
		try {
			await mutation.mutateAsync({ id: quote.id, data: { currency, rate: nextRate, reason: reason.trim() } });
			toast.success(nextRate === null ? t('quote.fx.overrideCleared') : t('quote.fx.overrideSaved'));
			onOpenChange(false);
		} catch (error) {
			toast.error(translateApiError(error));
		}
	}

	function submit(event: FormEvent) {
		event.preventDefault();
		if (!rateValid || !reasonValid) return;
		void save(normalizedRate);
	}

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-md">
				<form onSubmit={submit} className="flex flex-col gap-4">
					<DialogHeader>
						<DialogTitle>{t('quote.fx.dialogTitle', { currency })}</DialogTitle>
						<DialogDescription>{t('quote.fx.dialogDescription')}</DialogDescription>
					</DialogHeader>

					{row?.snapshot_rate ? (
						<p className="rounded-md bg-muted px-3 py-2 text-sm">
							{t('quote.fx.line', {
								date: formatDate(row.snapshot_rate_date),
								currency,
								rate: formatFxRate(row.snapshot_rate),
							})}{' '}
							<span className="text-muted-foreground">({t(fxSourceLabelKey(row.snapshot_source))})</span>
						</p>
					) : (
						<p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
							{t('quote.fx.missing', { currency })}
						</p>
					)}

					<div className="flex flex-col gap-1.5">
						<Label htmlFor="fx-override-rate">{t('quote.fx.rateLabel', { currency })}</Label>
						<Input
							id="fx-override-rate"
							inputMode="decimal"
							autoComplete="off"
							value={rate}
							onChange={(event) => setRate(event.target.value)}
							placeholder={row?.snapshot_rate ?? ''}
							aria-invalid={rate !== '' && !rateValid}
						/>
						{rate !== '' && !rateValid && (
							<p className="text-xs text-destructive">{t('quote.fx.rateInvalid')}</p>
						)}
					</div>

					<div className="flex flex-col gap-1.5">
						<Label htmlFor="fx-override-reason">{t('quote.fx.reasonLabel')}</Label>
						<Textarea
							id="fx-override-reason"
							rows={3}
							maxLength={REASON_MAX}
							value={reason}
							onChange={(event) => setReason(event.target.value)}
							placeholder={t('quote.fx.reasonPlaceholder')}
						/>
						<p className="text-xs text-muted-foreground">{t('quote.fx.reasonHelp')}</p>
					</div>

					<DialogFooter className="gap-2 sm:justify-between">
						{row?.override ? (
							<Button
								type="button"
								variant="outline"
								disabled={!reasonValid || mutation.isPending}
								onClick={() => void save(null)}
							>
								{t('quote.fx.clearOverride')}
							</Button>
						) : (
							<span />
						)}
						<div className="flex flex-col-reverse gap-2 sm:flex-row">
							<Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
								{t('common.cancel')}
							</Button>
							<Button type="submit" disabled={!rateValid || !reasonValid || mutation.isPending}>
								{mutation.isPending && <Loader2 className="size-4 animate-spin" />}
								{t('quote.fx.saveOverride')}
							</Button>
						</div>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
