import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Plus, Trash2, Loader2, Pencil, Check, X, ArrowUp, ArrowDown } from 'lucide-react';
import {
	useQuote,
	useQuoteCharges, useChargeTypes, useCreateQuoteCharge, useUpdateQuoteCharge, useDeleteQuoteCharge,
	useReorderQuoteCharges,
} from '@/hooks/useCRM';
import type { QuoteCharge } from '@/api/crmApi';
import { formatMoney } from '@/utils/decimal';
import { ChargeCascadeTable } from './ChargeCascadeTable';
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

type Mode = 'fixed' | 'percent';
type Kind = 'charge' | 'discount';

/**
 * КП-level expense items / discounts (UBL document AllowanceCharge). Seller-only —
 * the buyer never receives these rows. Each charge is a fixed sum OR a % of the
 * line subtotal, added (+) or deducted (−) before VAT. Rows are inline-editable
 * (amount/%/kind/description + the seller's real cost) — not just add+delete.
 */
export const QuoteChargesSection: React.FC<QuoteChargesSectionProps> = ({ quoteId, currency }) => {
	const { t } = useTranslation();
	const { data: quote } = useQuote(quoteId);
	const { data: charges = [] } = useQuoteCharges(quoteId);
	const { data: chargeTypes = [] } = useChargeTypes();
	const createMutation = useCreateQuoteCharge();
	const updateMutation = useUpdateQuoteCharge();
	const deleteMutation = useDeleteQuoteCharge();
	const reorderMutation = useReorderQuoteCharges();

	// Move a charge up/down in the cascade (swap with its neighbour) → resend the full order.
	const move = (index: number, dir: -1 | 1) => {
		const next = index + dir;
		if (next < 0 || next >= charges.length) return;
		const ids = charges.map((c) => c.id);
		[ids[index], ids[next]] = [ids[next], ids[index]];
		reorderMutation.mutate({ quoteId, order: ids });
	};

	// Add-row state
	const [chargeType, setChargeType] = useState('');
	const [value, setValue] = useState('');
	const [description, setDescription] = useState('');
	const [mode, setMode] = useState<Mode>('fixed');
	const [kind, setKind] = useState<Kind>('charge');

	// Inline-edit state (one row at a time)
	const [editingId, setEditingId] = useState<number | null>(null);
	const [editValue, setEditValue] = useState('');
	const [editCost, setEditCost] = useState('');
	const [editDescription, setEditDescription] = useState('');
	const [editMode, setEditMode] = useState<Mode>('fixed');
	const [editKind, setEditKind] = useState<Kind>('charge');
	const [deletingId, setDeletingId] = useState<number | null>(null);

	const ccyLabel = currency || 'UZS';

	const handleAdd = async () => {
		if (!chargeType || !value.trim()) return;
		try {
			await createMutation.mutateAsync({
				quote: quoteId,
				charge_type: chargeType,
				is_deduction: kind === 'discount',
				description: description.trim() || undefined,
				...(mode === 'percent' ? { rate_percent: value } : { amount: value }),
			});
			setValue('');
			setDescription('');
			setChargeType('');
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	};

	const startEdit = (charge: QuoteCharge) => {
		setEditingId(charge.id);
		setEditKind(charge.is_deduction ? 'discount' : 'charge');
		const isPercent = charge.rate_percent != null;
		setEditMode(isPercent ? 'percent' : 'fixed');
		setEditValue(isPercent ? String(charge.rate_percent) : String(charge.amount));
		setEditCost(charge.cost_amount != null ? String(charge.cost_amount) : '');
		setEditDescription(charge.description || '');
	};

	const cancelEdit = () => setEditingId(null);

	const saveEdit = async (id: number) => {
		if (!editValue.trim()) return;
		try {
			await updateMutation.mutateAsync({
				id,
				data: {
					is_deduction: editKind === 'discount',
					description: editDescription.trim(),
					// Switch unit cleanly: one of amount/rate_percent is the live value, the other cleared.
					...(editMode === 'percent'
						? { rate_percent: editValue, amount: '0' }
						: { rate_percent: null, amount: editValue }),
					// «Ваша стоимость» only for charges; a discount has no seller cost. Empty ⇒ null (pass-through).
					cost_amount: editKind === 'discount' ? null : (editCost.trim() ? editCost : null),
				},
			});
			setEditingId(null);
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	};

	const handleDelete = async (id: number) => {
		setDeletingId(id);
		try {
			await deleteMutation.mutateAsync(id);
		} catch {
			toast.error(t('errors.operationFailed'));
		} finally {
			setDeletingId(null);
		}
	};

	return (
		<Card className="py-3">
			<CardContent className="flex flex-col gap-2 py-0">
				<div className="flex items-center justify-between">
					<h3 className="text-sm font-semibold">{t('quote.charges.title')}</h3>
					<span className="text-xs text-muted-foreground">{t('quote.charges.beforeVat')}</span>
				</div>

				{/* Existing charges — inline-editable */}
				{charges.length > 0 && (
					<div className="flex flex-col divide-y rounded-md border">
						{charges.map((charge, index) => (
							editingId === charge.id ? (
								<div key={charge.id} className="flex flex-col gap-2 bg-muted/30 px-3 py-2">
									<div className="flex flex-wrap items-center gap-2">
										<span className="text-sm font-medium">{charge.charge_type_name || charge.charge_type}</span>
										<ToggleGroup type="single" value={editKind} onValueChange={(v) => v && setEditKind(v as Kind)} variant="outline" size="sm">
											<ToggleGroupItem value="charge">{t('quote.charges.charge')}</ToggleGroupItem>
											<ToggleGroupItem value="discount">{t('quote.charges.discount')}</ToggleGroupItem>
										</ToggleGroup>
										<ToggleGroup type="single" value={editMode} onValueChange={(v) => v && setEditMode(v as Mode)} variant="outline" size="sm">
											<ToggleGroupItem value="fixed">{t('quote.charges.sum')}</ToggleGroupItem>
											<ToggleGroupItem value="percent">%</ToggleGroupItem>
										</ToggleGroup>
										<Input
											type="number"
											min={0}
											max={editMode === 'percent' ? 100 : undefined}
											value={editValue}
											onChange={(e) => setEditValue(e.target.value)}
											placeholder={editMode === 'percent' ? '%' : t('quote.charges.amount')}
											className="h-8 w-24 text-sm"
											aria-label={t('quote.charges.amount')}
										/>
										{editKind === 'charge' && (
											<Input
												type="number"
												min={0}
												value={editCost}
												onChange={(e) => setEditCost(e.target.value)}
												placeholder={t('quote.charges.costAmount')}
												title={t('quote.charges.costAmountHint', { currency: ccyLabel })}
												className="h-8 w-32 text-sm"
												aria-label={t('quote.charges.costAmount')}
											/>
										)}
										<Button size="icon-xs" onClick={() => saveEdit(charge.id)} disabled={!editValue.trim() || updateMutation.isPending} title={t('common.save')}>
											{updateMutation.isPending ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
										</Button>
										<Button variant="ghost" size="icon-xs" onClick={cancelEdit} title={t('common.cancel')}>
											<X className="size-3" />
										</Button>
									</div>
									<Input
										type="text"
										value={editDescription}
										onChange={(e) => setEditDescription(e.target.value)}
										placeholder={t('quote.charges.descriptionPlaceholder')}
										className="h-8 text-sm"
										aria-label={t('quote.charges.description')}
									/>
								</div>
							) : (
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
										{/* Cascade base hint for a % row: «10% от <running base>» (transparency). */}
										{charge.rate_percent != null && charge.resolved_base != null && (
											<span className="text-xs text-muted-foreground tabular-nums">
												{t('quote.charges.ofBase', { rate: charge.rate_percent, base: formatMoney(charge.resolved_base, currency) })}
											</span>
										)}
										{!charge.is_deduction && charge.cost_amount != null && (
											<span className="text-xs text-muted-foreground tabular-nums" title={t('quote.charges.costAmount')}>
												{t('quote.charges.costShort')} {formatMoney(charge.cost_amount, currency)}
											</span>
										)}
										<span className="text-sm font-mono tabular-nums" title={t('quote.charges.amount')}>
											{charge.resolved_amount != null
												? `${Number(charge.resolved_amount) < 0 ? '−' : '+'}${formatMoney(String(Math.abs(Number(charge.resolved_amount))), currency)}`
												: charge.rate_percent != null
													? `${charge.is_deduction ? '−' : '+'}${charge.rate_percent}%`
													: `${charge.is_deduction ? '−' : '+'}${formatMoney(charge.amount, currency)}`}
										</span>
										<div className="flex flex-col">
											<Button variant="ghost" size="icon-xs" className="h-3.5 text-muted-foreground hover:text-foreground"
												onClick={() => move(index, -1)} disabled={index === 0 || reorderMutation.isPending} title={t('quote.charges.moveUp')}>
												<ArrowUp className="size-3" />
											</Button>
											<Button variant="ghost" size="icon-xs" className="h-3.5 text-muted-foreground hover:text-foreground"
												onClick={() => move(index, 1)} disabled={index === charges.length - 1 || reorderMutation.isPending} title={t('quote.charges.moveDown')}>
												<ArrowDown className="size-3" />
											</Button>
										</div>
										<Button
											variant="ghost"
											size="icon-xs"
											onClick={() => startEdit(charge)}
											className="text-muted-foreground hover:text-foreground"
											title={t('common.edit')}
										>
											<Pencil className="size-3" />
										</Button>
										<Button
											variant="ghost"
											size="icon-xs"
											onClick={() => handleDelete(charge.id)}
											disabled={deletingId === charge.id}
											className="text-muted-foreground hover:text-destructive"
											title={t('common.delete')}
										>
											{deletingId === charge.id ? <Loader2 className="size-3 animate-spin" /> : <Trash2 className="size-3" />}
										</Button>
									</div>
								</div>
							)
						))}
					</div>
				)}

				{/* Add charge row */}
				<div className="flex flex-wrap items-center gap-2">
					<Select value={chargeType} onValueChange={setChargeType}>
						<SelectTrigger className="h-8 w-full sm:w-[200px]" aria-label={t('quote.charges.type')}>
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

					<ToggleGroup type="single" value={kind} onValueChange={(v) => v && setKind(v as Kind)} variant="outline" size="sm">
						<ToggleGroupItem value="charge">{t('quote.charges.charge')}</ToggleGroupItem>
						<ToggleGroupItem value="discount">{t('quote.charges.discount')}</ToggleGroupItem>
					</ToggleGroup>

					{/* KP-08: this is a SUM-vs-PERCENT switch, not a currency picker. Charges are always
					    in the КП currency (label below); only line COSTS can be USD/EUR. */}
					<ToggleGroup type="single" value={mode} onValueChange={(v) => v && setMode(v as Mode)} variant="outline" size="sm">
						<ToggleGroupItem value="fixed">{t('quote.charges.sum')}</ToggleGroupItem>
						<ToggleGroupItem value="percent">%</ToggleGroupItem>
					</ToggleGroup>

					<Input
						type="number"
						min={0}
						max={mode === 'percent' ? 100 : undefined}
						value={value}
						onChange={(e) => setValue(e.target.value)}
						onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
						placeholder={mode === 'percent' ? '%' : t('quote.charges.amount')}
						className="h-8 w-24 text-sm"
					/>
					<Input
						type="text"
						value={description}
						onChange={(e) => setDescription(e.target.value)}
						onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
						placeholder={t('quote.charges.descriptionPlaceholder')}
						className="h-8 w-44 text-sm"
						aria-label={t('quote.charges.description')}
					/>
					<Button size="sm" onClick={handleAdd} disabled={!chargeType || !value.trim() || createMutation.isPending}>
						{createMutation.isPending ? <Loader2 className="size-3 animate-spin" /> : <Plus className="size-3" />}
						{t('common.add')}
					</Button>
				</div>
				<p className="text-xs text-muted-foreground">{t('quote.charges.inCurrency', { currency: ccyLabel })}</p>

				{/* Transparent price cascade: subtotal → charges (running) → tax base → +VAT → total.
				    Mirrors recalculate_quote to the копейка; presentation prices only (buyer-safe),
				    margin badge withheld unless the viewer may see cost/margin (economics present). */}
				{quote && (
					<ChargeCascadeTable
						subtotal={quote.subtotal_excl_vat}
						charges={charges}
						vatRate={quote.vat_rate}
						currency={ccyLabel}
						economics={quote.economics}
					/>
				)}
			</CardContent>
		</Card>
	);
};
