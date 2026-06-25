import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Plus, Trash2, Loader2 } from 'lucide-react';
import {
	useQuoteCharges, useChargeTypes, useCreateQuoteCharge, useDeleteQuoteCharge,
} from '@/hooks/useCRM';
import { formatMoney } from '@/utils/decimal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import {
	Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

interface QuoteChargesSectionProps {
	quoteId: number;
	currency?: string;
}

// CUSTOMS duty is the one cost computed PER LINE (rate by ТНВЭД) — offering it as a
// document-level charge would double-bill it. Everything else (freight/logistics,
// insurance, packing, …) is a batch/header charge entered here once (F3.8). Code (Rule 2).
const PER_LINE_CHARGE_CODES = ['CUSTOMS'];

/**
 * КП-level expense items / discounts (UBL document AllowanceCharge). Seller-only —
 * the buyer never receives these rows. Each charge is a fixed sum OR a % of the
 * line subtotal, added (+) or deducted (−) before VAT.
 */
export const QuoteChargesSection: React.FC<QuoteChargesSectionProps> = ({ quoteId, currency }) => {
	const { t } = useTranslation();
	const { data: charges = [] } = useQuoteCharges(quoteId);
	const { data: chargeTypes = [] } = useChargeTypes();
	const createMutation = useCreateQuoteCharge();
	const deleteMutation = useDeleteQuoteCharge();

	const [chargeType, setChargeType] = useState('');
	const [value, setValue] = useState('');
	const [mode, setMode] = useState<'fixed' | 'percent'>('fixed');
	const [kind, setKind] = useState<'charge' | 'discount'>('charge');

	const handleAdd = async () => {
		if (!chargeType || !value.trim()) return;
		try {
			await createMutation.mutateAsync({
				quote: quoteId,
				charge_type: chargeType,
				is_deduction: kind === 'discount',
				...(mode === 'percent' ? { rate_percent: value } : { amount: value }),
			});
			setValue('');
			setChargeType('');
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	};

	return (
		<Card className="py-3">
			<CardContent className="flex flex-col gap-2 py-0">
				<div className="flex items-center justify-between">
					<h3 className="text-sm font-semibold">{t('quote.charges.title')}</h3>
					<span className="text-xs text-muted-foreground">{t('quote.charges.beforeVat')}</span>
				</div>

				{/* Existing charges */}
				{charges.length > 0 && (
					<div className="flex flex-col divide-y rounded-md border">
						{charges.map((charge) => (
							<div key={charge.id} className="flex items-center justify-between px-3 py-1.5">
								<div className="flex items-center gap-2 min-w-0">
									<Badge variant={charge.is_deduction ? 'secondary' : 'outline'} className="shrink-0">
										{charge.is_deduction ? t('quote.charges.discount') : t('quote.charges.charge')}
									</Badge>
									<span className="text-sm font-medium truncate">{charge.charge_type_name || charge.charge_type}</span>
									{charge.description && (
										<span className="text-xs text-muted-foreground truncate">— {charge.description}</span>
									)}
								</div>
								<div className="flex items-center gap-3 shrink-0">
									<span className="text-sm font-mono tabular-nums">
										{charge.rate_percent != null
											? `${charge.is_deduction ? '−' : '+'}${charge.rate_percent}%`
											: `${charge.is_deduction ? '−' : '+'}${formatMoney(charge.amount, currency)}`}
									</span>
									<Button
										variant="ghost"
										size="icon-xs"
										onClick={() => deleteMutation.mutate(charge.id)}
										className="text-muted-foreground hover:text-destructive"
										title={t('common.delete')}
									>
										<Trash2 className="size-3" />
									</Button>
								</div>
							</div>
						))}
					</div>
				)}

				{/* Add charge row */}
				<div className="flex flex-wrap items-center gap-2">
					<Select value={chargeType} onValueChange={setChargeType}>
						<SelectTrigger className="h-8 w-[200px]" aria-label={t('quote.charges.type')}>
							<SelectValue placeholder={t('quote.charges.typePlaceholder')} />
						</SelectTrigger>
						<SelectContent>
							{/* Freight & customs are PER-LINE columns (Логистика/Таможня) in the builder —
							    offering them as КП-level charges double-bills them (audit M3: only
							    non-line costs like insurance/certification belong at document level). */}
							{chargeTypes
								.filter((ct) => !PER_LINE_CHARGE_CODES.includes(ct.code))
								.map((ct) => (
									<SelectItem key={ct.id} value={ct.code}>{ct.name}</SelectItem>
								))}
						</SelectContent>
					</Select>

					<ToggleGroup type="single" value={kind} onValueChange={(v) => v && setKind(v as 'charge' | 'discount')} variant="outline" size="sm">
						<ToggleGroupItem value="charge">{t('quote.charges.charge')}</ToggleGroupItem>
						<ToggleGroupItem value="discount">{t('quote.charges.discount')}</ToggleGroupItem>
					</ToggleGroup>

					<ToggleGroup type="single" value={mode} onValueChange={(v) => v && setMode(v as 'fixed' | 'percent')} variant="outline" size="sm">
						<ToggleGroupItem value="fixed">{currency || t('quote.charges.sum')}</ToggleGroupItem>
						<ToggleGroupItem value="percent">%</ToggleGroupItem>
					</ToggleGroup>

					<Input
						type="number"
						value={value}
						onChange={(e) => setValue(e.target.value)}
						onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
						placeholder={mode === 'percent' ? '%' : t('quote.charges.amount')}
						className="h-8 w-28 text-sm"
					/>
					<Button size="sm" onClick={handleAdd} disabled={!chargeType || !value.trim() || createMutation.isPending}>
						{createMutation.isPending ? <Loader2 className="size-3 animate-spin" /> : <Plus className="size-3" />}
						{t('common.add')}
					</Button>
				</div>
			</CardContent>
		</Card>
	);
};
