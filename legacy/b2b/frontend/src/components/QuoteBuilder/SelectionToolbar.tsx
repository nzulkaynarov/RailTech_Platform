import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Copy, Percent, Tag, Trash2, X, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
	Popover, PopoverContent, PopoverTrigger,
} from '@/components/ui/popover';
import {
	AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
	AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from '@/components/ui/alert-dialog';

interface SelectionToolbarProps {
	count: number;
	/** Bulk delete of the selected rows (opens its own confirm). */
	onDelete: () => void;
	/** Apply a flat discount % to the selected rows (LOCAL draft edit — 0..100). */
	onApplyDiscount: (percent: number) => void;
	/** Change the base price of the selected rows by ±% (LOCAL draft edit). */
	onApplyPriceChange: (percent: number) => void;
	/** Duplicate the selected rows (bulk-create). */
	onDuplicate: () => void;
	/** Clear the selection without acting. */
	onClear: () => void;
	deleting?: boolean;
	duplicating?: boolean;
}

/** Parse a locale-friendly number (comma decimal, grouping spaces) or null when unparseable. */
const parsePercent = (raw: string): number | null => {
	const normalized = raw.replace(/,/g, '.').replace(/\s/g, '');
	if (normalized === '' || normalized === '-' || normalized === '+') return null;
	const value = Number(normalized);
	return Number.isFinite(value) ? value : null;
};

/**
 * The bulk-action strip shown above the КП line table while ≥1 row is selected
 * (WP-J / spec §5 волна 2 п.11). Delete asks one confirm; the discount / price-change
 * popovers apply a LOCAL draft edit (live recalc + Save via the existing bulk-update);
 * duplicate goes through the bulk-create endpoint.
 */
export const SelectionToolbar: React.FC<SelectionToolbarProps> = ({
	count,
	onDelete,
	onApplyDiscount,
	onApplyPriceChange,
	onDuplicate,
	onClear,
	deleting,
	duplicating,
}) => {
	const { t } = useTranslation();
	const [discountValue, setDiscountValue] = useState('');
	const [priceValue, setPriceValue] = useState('');
	const [discountOpen, setDiscountOpen] = useState(false);
	const [priceOpen, setPriceOpen] = useState(false);

	const applyDiscount = () => {
		const percent = parsePercent(discountValue);
		if (percent == null) return;
		const clamped = Math.min(100, Math.max(0, percent));
		// Discount is bounded to 0..100 — warn (not silently) when the entry was corrected, so the
		// seller sees that a «150» became «100». The clamped (safe) value is still applied.
		if (clamped !== percent) toast.warning(t('quote.validation.discountClamped'));
		onApplyDiscount(clamped);
		setDiscountValue('');
		setDiscountOpen(false);
	};

	const applyPriceChange = () => {
		const percent = parsePercent(priceValue);
		if (percent == null) return;
		onApplyPriceChange(percent);
		setPriceValue('');
		setPriceOpen(false);
	};

	return (
		<div className="flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-1.5">
			<span className="text-sm font-medium text-foreground">{t('quote.bulk.selected', { count })}</span>

			{/* Delete selected — one confirm for the whole batch. */}
			<AlertDialog>
				<AlertDialogTrigger asChild>
					<Button variant="outline" size="sm" disabled={deleting}>
						{deleting ? <Loader2 className="size-3 animate-spin" /> : <Trash2 className="size-3" />}
						{t('quote.bulk.delete')}
					</Button>
				</AlertDialogTrigger>
				<AlertDialogContent>
					<AlertDialogHeader>
						<AlertDialogTitle>{t('quote.bulk.deleteConfirmTitle')}</AlertDialogTitle>
						<AlertDialogDescription>
							{t('quote.bulk.deleteConfirmDescription', { count })}
						</AlertDialogDescription>
					</AlertDialogHeader>
					<AlertDialogFooter>
						<AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
						<AlertDialogAction onClick={onDelete}>{t('common.delete')}</AlertDialogAction>
					</AlertDialogFooter>
				</AlertDialogContent>
			</AlertDialog>

			{/* Bulk discount % — a LOCAL draft edit applied to every selected row. */}
			<Popover open={discountOpen} onOpenChange={setDiscountOpen}>
				<PopoverTrigger asChild>
					<Button variant="outline" size="sm">
						<Percent className="size-3" />
						{t('quote.bulk.discount')}
					</Button>
				</PopoverTrigger>
				<PopoverContent className="w-56" align="start">
					<div className="flex flex-col gap-2">
						<Label htmlFor="bulk-discount" className="text-xs">{t('quote.bulk.discountLabel')}</Label>
						<div className="flex items-center gap-2">
							<Input
								id="bulk-discount"
								type="text"
								inputMode="decimal"
								value={discountValue}
								onChange={(event) => setDiscountValue(event.target.value)}
								onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); applyDiscount(); } }}
								className="h-8 text-sm"
								placeholder="0"
								aria-label={t('quote.bulk.discountLabel')}
							/>
							<Button size="sm" onClick={applyDiscount} disabled={parsePercent(discountValue) == null}>
								{t('quote.bulk.apply')}
							</Button>
						</div>
					</div>
				</PopoverContent>
			</Popover>

			{/* Bulk price change ±% — a LOCAL draft edit applied to every selected row's base price. */}
			<Popover open={priceOpen} onOpenChange={setPriceOpen}>
				<PopoverTrigger asChild>
					<Button variant="outline" size="sm">
						<Tag className="size-3" />
						{t('quote.bulk.priceChange')}
					</Button>
				</PopoverTrigger>
				<PopoverContent className="w-64" align="start">
					<div className="flex flex-col gap-2">
						<Label htmlFor="bulk-price" className="text-xs">{t('quote.bulk.priceChangeLabel')}</Label>
						<div className="flex items-center gap-2">
							<Input
								id="bulk-price"
								type="text"
								inputMode="decimal"
								value={priceValue}
								onChange={(event) => setPriceValue(event.target.value)}
								onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); applyPriceChange(); } }}
								className="h-8 text-sm"
								placeholder={t('quote.bulk.priceChangeHint')}
								aria-label={t('quote.bulk.priceChangeLabel')}
							/>
							<Button size="sm" onClick={applyPriceChange} disabled={parsePercent(priceValue) == null}>
								{t('quote.bulk.apply')}
							</Button>
						</div>
						<span className="text-xs text-muted-foreground">{t('quote.bulk.priceChangeHelp')}</span>
					</div>
				</PopoverContent>
			</Popover>

			{/* Duplicate selected → bulk-create «(копия)» lines. */}
			<Button variant="outline" size="sm" onClick={onDuplicate} disabled={duplicating}>
				{duplicating ? <Loader2 className="size-3 animate-spin" /> : <Copy className="size-3" />}
				{t('quote.bulk.duplicate')}
			</Button>

			<Button variant="ghost" size="sm" onClick={onClear} className="ml-auto text-muted-foreground">
				<X className="size-3" />
				{t('quote.bulk.clearSelection')}
			</Button>
		</div>
	);
};
