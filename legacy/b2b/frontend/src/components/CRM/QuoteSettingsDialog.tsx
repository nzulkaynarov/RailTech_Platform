import { FormEvent, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import { Quote } from '@/api/crmApi';
import { useUpdateQuoteSettings } from '@/hooks/useCRM';
import { useCountries, useCurrencies } from '@/hooks/useMasterData';
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

interface QuoteSettingsDialogProps {
	quote: Quote;
	open: boolean;
	onOpenChange: (open: boolean) => void;
}

// Client-side bounds for the VAT rate (%). The backend is the source of truth, but
// these stop a seller from typing nonsense like 999 and get fast inline feedback.
const VAT_RATE_MIN = 0;
const VAT_RATE_MAX = 100;

// Seller-only КП settings: VAT rate (%), tax country, valid until (date), currency.
// Currency is sent as the Currency CODE (e.g. "UZS") to match the backend SlugRelatedField;
// tax country is sent as the Country pk. Frozen КП is read-only (backend rejects with
// QUOTE_FROZEN), but the gear button is hidden in that case upstream.
export function QuoteSettingsDialog({ quote, open, onOpenChange }: QuoteSettingsDialogProps) {
	const { t } = useTranslation();
	const { data: countries = [] } = useCountries();
	const { data: currencies = [] } = useCurrencies();
	const updateSettings = useUpdateQuoteSettings();

	const [marginPercent, setMarginPercent] = useState('');
	const [vatRate, setVatRate] = useState('');
	const [taxCountry, setTaxCountry] = useState('');
	const [validUntil, setValidUntil] = useState('');
	const [currency, setCurrency] = useState('');

	const vatRateNumber = vatRate === '' ? null : Number(vatRate);
	const vatRateInvalid =
		vatRateNumber !== null &&
		(Number.isNaN(vatRateNumber) || vatRateNumber < VAT_RATE_MIN || vatRateNumber > VAT_RATE_MAX);

	// Re-seed the form from the КП whenever it opens (the seller may switch quotes).
	useEffect(() => {
		if (!open) return;
		setMarginPercent(quote.margin_percent ?? '');
		setVatRate(quote.vat_rate ?? '');
		setTaxCountry(quote.tax_country != null ? String(quote.tax_country) : '');
		setValidUntil(quote.valid_until ?? '');
		setCurrency(quote.quote_currency ?? '');
	}, [open, quote]);

	async function submit(event: FormEvent) {
		event.preventDefault();
		if (vatRateInvalid) {
			toast.error(t('quote.settings.vatRateOutOfRange', { min: VAT_RATE_MIN, max: VAT_RATE_MAX }));
			return;
		}
		try {
			await updateSettings.mutateAsync({
				id: quote.id,
				data: {
					margin_percent: marginPercent === '' ? undefined : marginPercent,
					vat_rate: vatRate === '' ? undefined : vatRate,
					tax_country: taxCountry === '' ? null : Number(taxCountry),
					valid_until: validUntil === '' ? null : validUntil,
					quote_currency: currency === '' ? null : currency,
				},
			});
			toast.success(t('quote.settings.saved'));
			onOpenChange(false);
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	}

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-md">
				<form onSubmit={submit}>
					<DialogHeader>
						<DialogTitle>{t('quote.settings.title')}</DialogTitle>
						<DialogDescription>{t('quote.settings.description')}</DialogDescription>
					</DialogHeader>

					<div className="mt-4 flex flex-col gap-4">
						<div className="flex flex-col gap-1.5">
							<Label htmlFor="quote-margin">{t('quote.settings.margin')}</Label>
							<Input id="quote-margin" type="number" step="0.01" min={0} value={marginPercent} onChange={(e) => setMarginPercent(e.target.value)} />
							<p className="text-xs text-muted-foreground">{t('quote.settings.marginHelp')}</p>
						</div>
						<div className="flex flex-col gap-1.5">
							<Label htmlFor="quote-vat-rate">{t('quote.settings.vatRate')}</Label>
							<Input
								id="quote-vat-rate"
								type="number"
								step="0.01"
								min={VAT_RATE_MIN}
								max={VAT_RATE_MAX}
								value={vatRate}
								onChange={(event) => setVatRate(event.target.value)}
								aria-invalid={vatRateInvalid}
							/>
							{vatRateInvalid && (
								<p className="text-xs text-destructive">
									{t('quote.settings.vatRateOutOfRange', { min: VAT_RATE_MIN, max: VAT_RATE_MAX })}
								</p>
							)}
						</div>

						<div className="flex flex-col gap-1.5">
							<Label htmlFor="quote-tax-country">{t('quote.settings.taxCountry')}</Label>
							<Select value={taxCountry} onValueChange={setTaxCountry}>
								<SelectTrigger id="quote-tax-country">
									<SelectValue placeholder={t('quote.settings.taxCountryPlaceholder')} />
								</SelectTrigger>
								<SelectContent>
									{countries.map((country) => (
										<SelectItem key={country.id} value={String(country.id)}>
											{country.name}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>

						<div className="flex flex-col gap-1.5">
							<Label htmlFor="quote-valid-until">{t('quote.settings.validUntil')}</Label>
							<Input
								id="quote-valid-until"
								type="date"
								value={validUntil}
								onChange={(event) => setValidUntil(event.target.value)}
							/>
						</div>

						<div className="flex flex-col gap-1.5">
							<Label htmlFor="quote-currency">{t('quote.settings.currency')}</Label>
							<Select value={currency} onValueChange={setCurrency}>
								<SelectTrigger id="quote-currency">
									<SelectValue placeholder={t('quote.settings.currencyPlaceholder')} />
								</SelectTrigger>
								<SelectContent>
									{currencies.map((item) => (
										<SelectItem key={item.id} value={item.code}>
											{item.code} — {item.name}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>
					</div>

					<DialogFooter className="mt-6 gap-2">
						<Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
							{t('common.cancel')}
						</Button>
						<Button type="submit" disabled={updateSettings.isPending || vatRateInvalid}>
							{updateSettings.isPending && <Loader2 className="size-4 animate-spin" />}
							{t('common.save')}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
