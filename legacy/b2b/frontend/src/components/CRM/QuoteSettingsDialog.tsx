import { FormEvent, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import { Quote } from '@/api/crmApi';
import { useUpdateQuoteSettings, useSetQuoteDeliveryBasis } from '@/hooks/useCRM';
import { useCountries, useCurrencies } from '@/hooks/useMasterData';
import { DeliveryBasisSelect } from './DeliveryBasisSelect';
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
	// Delivery basis (Incoterm) has its OWN endpoint (auto-applies the charge template), so it
	// applies immediately on change rather than waiting for Save — same behaviour as the old rail
	// select, just relocated here (S2 consolidation).
	const setBasis = useSetQuoteDeliveryBasis();

	const [marginPercent, setMarginPercent] = useState('');
	const [vatRate, setVatRate] = useState('');
	const [taxCountry, setTaxCountry] = useState('');
	const [validUntil, setValidUntil] = useState('');
	const [currency, setCurrency] = useState('');
	const [costCurrencyDefault, setCostCurrencyDefault] = useState('');
	const [deliveryLeadTime, setDeliveryLeadTime] = useState('');
	const [deliveryNote, setDeliveryNote] = useState('');
	// КП-level manual FX overrides keyed by currency code (empty ⇒ use CBU snapshot).
	const [fxManual, setFxManual] = useState<Record<string, string>>({});

	// Currencies the engine has frozen an FX snapshot for — the rows of the FX editor.
	const fxSnapshot = quote.fx_snapshot ?? {};
	const fxCurrencies = Object.keys(fxSnapshot);

	const vatRateNumber = vatRate === '' ? null : Number(vatRate);
	const vatRateInvalid =
		vatRateNumber !== null &&
		(Number.isNaN(vatRateNumber) || vatRateNumber < VAT_RATE_MIN || vatRateNumber > VAT_RATE_MAX);

	// Seed the form from the КП when the dialog OPENS or the seller switches to a
	// different КП — keyed on quote.id, never on the `quote` object reference. Saving
	// invalidates ['quotes'] (useUpdateQuoteSettings), so a background refetch hands us
	// a fresh `quote` object mid-edit; re-seeding on that reference change would silently
	// overwrite the value the seller just typed (P2-3 silent-save). The ref guard makes
	// the seed idempotent per open КП, so those refetches leave the form untouched.
	const seededQuoteIdRef = useRef<number | null>(null);
	useEffect(() => {
		if (!open) {
			seededQuoteIdRef.current = null;
			return;
		}
		if (seededQuoteIdRef.current === quote.id) return;
		seededQuoteIdRef.current = quote.id;
		setMarginPercent(quote.margin_percent ?? '');
		setVatRate(quote.vat_rate ?? '');
		setTaxCountry(quote.tax_country != null ? String(quote.tax_country) : '');
		setValidUntil(quote.valid_until ?? '');
		setCurrency(quote.quote_currency ?? '');
		setCostCurrencyDefault(quote.cost_currency_default ?? '');
		setDeliveryLeadTime(quote.delivery_lead_time_days != null ? String(quote.delivery_lead_time_days) : '');
		setDeliveryNote(quote.delivery_note ?? '');
		setFxManual({ ...(quote.fx_manual ?? {}) });
	}, [open, quote]);

	// Edit a single currency's manual override; empty string clears it (back to CBU).
	const setOverride = (code: string, value: string) => {
		setFxManual((prev) => ({ ...prev, [code]: value }));
	};

	async function submit(event: FormEvent) {
		event.preventDefault();
		if (vatRateInvalid) {
			toast.error(t('quote.settings.vatRateOutOfRange', { min: VAT_RATE_MIN, max: VAT_RATE_MAX }));
			return;
		}
		// Keep only non-empty overrides — a blank input means "use the CBU snapshot".
		const cleanedFxManual = Object.fromEntries(
			Object.entries(fxManual).filter(([, rate]) => rate !== '' && rate != null),
		);
		try {
			await updateSettings.mutateAsync({
				id: quote.id,
				data: {
					margin_percent: marginPercent === '' ? undefined : marginPercent,
					vat_rate: vatRate === '' ? undefined : vatRate,
					tax_country: taxCountry === '' ? null : Number(taxCountry),
					valid_until: validUntil === '' ? null : validUntil,
					quote_currency: currency === '' ? null : currency,
					cost_currency_default: costCurrencyDefault === '' ? null : costCurrencyDefault,
					delivery_lead_time_days: deliveryLeadTime === '' ? null : Number(deliveryLeadTime),
					delivery_note: deliveryNote,
					fx_manual: cleanedFxManual,
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
			<DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-md">
				<form onSubmit={submit}>
					<DialogHeader>
						<DialogTitle>{t('quote.settings.title')}</DialogTitle>
						<DialogDescription>{t('quote.settings.description')}</DialogDescription>
					</DialogHeader>

					<div className="mt-4 flex flex-col gap-4">
						{/* Поставка (S2): базис поставки (Incoterm) переехал сюда из правой панели грида.
						    Применяется сразу при выборе — движок пересчитывает статьи затрат по базису. */}
						<div className="flex flex-col gap-1.5">
							<span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
								{t('quote.settings.deliverySection')}
							</span>
							<DeliveryBasisSelect
								value={quote.delivery_basis}
								onChange={(basisId) => setBasis.mutate({ id: quote.id, deliveryBasis: basisId })}
								disabled={!!quote.frozen_at || setBasis.isPending}
							/>
							<p className="text-xs text-muted-foreground">{t('quote.settings.deliveryBasisHelp')}</p>
						</div>

						<div className="flex flex-col gap-1.5">
							<Label htmlFor="quote-margin">{t('quote.settings.margin')}</Label>
							<Input
								id="quote-margin"
								type="number"
								step="0.01"
								min={0}
								value={marginPercent}
								onChange={(event) => setMarginPercent(event.target.value)}
								onFocus={(event) => event.target.select()}
							/>
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
								onFocus={(event) => event.target.select()}
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
							{/* The КП presentation currency is UZS: the cost engine converts EVERY line
							    (USD/EUR/…) to UZS via a frozen FX rate, so subtotal/VAT/total are stored
							    in UZS. Offering another quote_currency here would only MISLABEL those UZS
							    amounts (the builder + PDF print quote_currency's code). Restrict to UZS
							    until the engine can target a non-UZS presentation currency. Per-line COST
							    currency stays multi-currency below. */}
							<Select value={currency} onValueChange={setCurrency}>
								<SelectTrigger id="quote-currency">
									<SelectValue placeholder={t('quote.settings.currencyPlaceholder')} />
								</SelectTrigger>
								<SelectContent>
									{currencies.filter((item) => item.code === 'UZS').map((item) => (
										<SelectItem key={item.id} value={item.code}>
											{item.code} — {item.name}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
							<p className="text-xs text-muted-foreground">{t('quote.settings.currencyHelp')}</p>
						</div>

						<div className="flex flex-col gap-1.5">
							<Label htmlFor="quote-cost-currency">{t('quote.settings.costCurrencyDefault')}</Label>
							<Select value={costCurrencyDefault} onValueChange={setCostCurrencyDefault}>
								<SelectTrigger id="quote-cost-currency">
									<SelectValue placeholder={t('quote.settings.costCurrencyDefaultPlaceholder')} />
								</SelectTrigger>
								<SelectContent>
									{currencies.map((item) => (
										<SelectItem key={item.id} value={item.code}>
											{item.code} — {item.name}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
							<p className="text-xs text-muted-foreground">{t('quote.settings.costCurrencyDefaultHelp')}</p>
						</div>

						<div className="flex flex-col gap-1.5">
							<Label htmlFor="quote-lead-time">{t('quote.settings.deliveryLeadTime')}</Label>
							<Input
								id="quote-lead-time"
								type="number"
								min={0}
								value={deliveryLeadTime}
								onChange={(event) => setDeliveryLeadTime(event.target.value)}
								onFocus={(event) => event.target.select()}
								placeholder={String(quote.effective_delivery_lead_time_days ?? 0)}
							/>
							<p className="text-xs text-muted-foreground">{t('quote.settings.deliveryLeadTimeHelp')}</p>
						</div>

						<div className="flex flex-col gap-1.5">
							<Label htmlFor="quote-delivery-note">{t('quote.settings.deliveryNote')}</Label>
							<Input
								id="quote-delivery-note"
								type="text"
								maxLength={255}
								value={deliveryNote}
								onChange={(event) => setDeliveryNote(event.target.value)}
								placeholder={t('quote.settings.deliveryNotePlaceholder')}
							/>
						</div>

						{/* Manual FX override editor — one row per currency the engine froze a rate
						    for. The CBU snapshot is shown read-only; the input writes fx_manual
						    (empty ⇒ keep CBU). Rates are сум per 1 unit of currency. */}
						{fxCurrencies.length > 0 && (
							<div className="flex flex-col gap-2">
								<Label>{t('quote.settings.fxOverride')}</Label>
								<p className="text-xs text-muted-foreground">{t('quote.settings.fxOverrideHelp')}</p>
								<div className="flex flex-col gap-2">
									{fxCurrencies.map((code) => (
										<div key={code} className="flex items-center gap-2">
											<span className="w-12 text-sm font-mono">{code}</span>
											<span className="flex-1 text-xs text-muted-foreground">
												{t('quote.settings.fxCbuRate', { rate: fxSnapshot[code] })}
											</span>
											<Input
												type="number"
												step="0.0001"
												min={0}
												className="w-32"
												aria-label={t('quote.settings.fxOverrideFor', { code })}
												value={fxManual[code] ?? ''}
												onChange={(event) => setOverride(code, event.target.value)}
												onFocus={(event) => event.target.select()}
												placeholder={fxSnapshot[code]}
											/>
										</div>
									))}
								</div>
							</div>
						)}
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
