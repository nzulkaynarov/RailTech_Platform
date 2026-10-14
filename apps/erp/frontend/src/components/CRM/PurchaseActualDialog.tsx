import { FormEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import type { MarginDeviationRow } from '@/api/financeApi';
import { useRecordPurchaseActual } from '@/hooks/useFinance';
import { translateApiError } from '@/lib/apiError';
import { formatMoney, toDecimal } from '@/utils/decimal';
import { formatFxRate } from '@/lib/fx';
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

const AMOUNT_PATTERN = /^\d{1,13}(\.\d{1,2})?$/;
const RATE_PATTERN = /^\d{1,12}(\.\d{1,6})?$/;
const normalize = (value: string) => value.trim().replace(/\s/g, '').replace(',', '.');

/**
 * Факт закупки по одной валюте сделки (M1-ERP-08; вручную до M4): сумма в валюте (пусто — как в
 * КП), фактический курс (по умолчанию — курс справочника на дату закупки), дата и комментарий.
 */
export function PurchaseActualDialog({
	dealId,
	row,
	onOpenChange,
}: {
	dealId: number;
	row: MarginDeviationRow;
	onOpenChange: (open: boolean) => void;
}) {
	const { t } = useTranslation();
	const mutation = useRecordPurchaseActual(dealId);
	const isBase = row.currency === 'UZS';
	const [amount, setAmount] = useState(row.actual_amount ?? '');
	const [rate, setRate] = useState(isBase ? '1' : (row.actual_rate ?? row.suggested_rate ?? ''));
	const [purchasedOn, setPurchasedOn] = useState(row.purchased_on ?? '');
	const [note, setNote] = useState(row.note ?? '');

	const amountValid = amount.trim() === '' || AMOUNT_PATTERN.test(normalize(amount));
	const rateValid = isBase || rate.trim() === '' || (RATE_PATTERN.test(normalize(rate)) && toDecimal(normalize(rate)).gt(0));

	async function submit(event: FormEvent) {
		event.preventDefault();
		if (!amountValid || !rateValid) return;
		try {
			await mutation.mutateAsync({
				currency: row.currency,
				amount: amount.trim() === '' ? null : normalize(amount),
				rate: isBase || rate.trim() === '' ? null : normalize(rate),
				purchased_on: purchasedOn || null,
				note: note.trim(),
			});
			toast.success(t('dealMargin.saved'));
			onOpenChange(false);
		} catch (error) {
			toast.error(translateApiError(error));
		}
	}

	return (
		<Dialog open onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-md">
				<form onSubmit={submit} className="flex flex-col gap-4">
					<DialogHeader>
						<DialogTitle>{t('dealMargin.dialogTitle', { currency: row.currency })}</DialogTitle>
						<DialogDescription>
							{t('dealMargin.dialogDescription', {
								amount: formatMoney(row.quoted_amount, row.currency),
								rate: formatFxRate(row.quoted_rate),
							})}
						</DialogDescription>
					</DialogHeader>

					<div className="flex flex-col gap-1.5">
						<Label htmlFor="purchase-amount">{t('dealMargin.amountLabel', { currency: row.currency })}</Label>
						<Input
							id="purchase-amount"
							inputMode="decimal"
							autoComplete="off"
							value={amount}
							onChange={(event) => setAmount(event.target.value)}
							placeholder={row.quoted_amount}
							aria-invalid={!amountValid}
						/>
						<p className={amountValid ? 'text-xs text-muted-foreground' : 'text-xs text-destructive'}>
							{amountValid ? t('dealMargin.amountHelp') : t('dealMargin.amountInvalid')}
						</p>
					</div>

					{!isBase && (
						<div className="flex flex-col gap-1.5">
							<Label htmlFor="purchase-rate">{t('dealMargin.rateLabel', { currency: row.currency })}</Label>
							<Input
								id="purchase-rate"
								inputMode="decimal"
								autoComplete="off"
								value={rate}
								onChange={(event) => setRate(event.target.value)}
								placeholder={row.suggested_rate ?? ''}
								aria-invalid={!rateValid}
							/>
							<p className={rateValid ? 'text-xs text-muted-foreground' : 'text-xs text-destructive'}>
								{!rateValid
									? t('quote.fx.rateInvalid')
									: row.suggested_rate
										? t('dealMargin.rateHelp', {
											rate: formatFxRate(row.suggested_rate),
											date: formatDate(row.suggested_rate_date),
										})
										: t('dealMargin.rateHelpNoRate')}
							</p>
						</div>
					)}

					<div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
						<div className="flex flex-col gap-1.5">
							<Label htmlFor="purchase-date">{t('dealMargin.dateLabel')}</Label>
							<Input
								id="purchase-date"
								type="date"
								value={purchasedOn}
								onChange={(event) => setPurchasedOn(event.target.value)}
							/>
						</div>
						<div className="flex flex-col gap-1.5">
							<Label htmlFor="purchase-note">{t('dealMargin.noteLabel')}</Label>
							<Input
								id="purchase-note"
								maxLength={500}
								value={note}
								onChange={(event) => setNote(event.target.value)}
								placeholder={t('dealMargin.notePlaceholder')}
							/>
						</div>
					</div>
					<p className="text-xs text-muted-foreground">{t('dealMargin.dateHelp')}</p>

					<DialogFooter className="gap-2">
						<Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
							{t('common.cancel')}
						</Button>
						<Button type="submit" disabled={!amountValid || !rateValid || mutation.isPending}>
							{mutation.isPending && <Loader2 className="size-4 animate-spin" />}
							{t('common.save')}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
