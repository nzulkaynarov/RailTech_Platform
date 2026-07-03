import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { QuoteItem, QuoteEconomics, crmApi } from '@/api/crmApi';
import { translateApiError } from '@/lib/apiError';
import {
	Loader2, Save, AlertTriangle, Plus, Trash2, Sparkles, FileText, Settings, Tag,
	ChevronRight, ChevronDown, PanelRightClose, PanelRightOpen, Link2,
} from 'lucide-react';
import { useQuoteItems, useUpdateQuoteItem, useCreateQuoteItem, useDeleteQuoteItem, useDeal, useSetQuoteDeliveryBasis } from '@/hooks/useCRM';
import { useCurrencies } from '@/hooks/useMasterData';
import { cn } from '@/lib/utils';
import { formatMoney, calculateLineTotal, toDecimal } from '@/utils/decimal';
import { DeliveryBasisSelect } from '@/components/CRM/DeliveryBasisSelect';
import { QuoteChargesSection } from '@/components/CRM/QuoteChargesSection';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import {
	Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { QuoteApprovalChain } from '@/components/CRM/QuoteApprovalChain';
import { AICatalogMatchDialog } from '@/components/Admin/AICatalogMatchDialog';
import { GenerateQuoteDialog } from '@/components/CRM/GenerateQuoteDialog';
import { QuoteSettingsDialog } from '@/components/CRM/QuoteSettingsDialog';
import { ReassignProductDialog } from '@/components/CRM/ReassignProductDialog';
import { ExportMenu } from '@/components/Shared/ExportMenu';

interface QuoteBuilderGridProps {
	dealId?: number;
	onSave?: () => void;
}

// Margin health → semantic color, shared by the КП-level rail and the per-line chip.
const marginToneClass = (belowCostOrFloor: boolean, marginPct: number, target: number): string =>
	belowCostOrFloor ? 'text-destructive' : marginPct >= target ? 'text-success' : 'text-warning';

// Compact, locale-aware money for the collapsed rail strip (e.g. «7,8 млн»). Locale follows
// the active i18n language (not hardcoded). Full value is always in the tooltip via formatMoney.
const compactNumber = (value: string | number | null | undefined, locale: string): string =>
	new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value || 0));

export const QuoteBuilderGrid: React.FC<QuoteBuilderGridProps> = ({ dealId: propDealId, onSave }) => {
	const { t, i18n } = useTranslation();
	const dealId = propDealId || 0;

	const { data: quoteItems = [], isLoading: itemsLoading } = useQuoteItems({ deal_id: dealId });
	const { data: deal, isLoading: dealLoading } = useDeal(dealId);
	const { data: currencies = [] } = useCurrencies();
	const updateMutation = useUpdateQuoteItem();
	const createItemMutation = useCreateQuoteItem();
	const deleteItemMutation = useDeleteQuoteItem();
	const setBasisMutation = useSetQuoteDeliveryBasis();

	const [localItems, setLocalItems] = useState<QuoteItem[]>([]);
	const [newItemName, setNewItemName] = useState('');
	const [showAddRow, setShowAddRow] = useState(false);
	const [showAiMatch, setShowAiMatch] = useState(false);
	const [showGenerateQuote, setShowGenerateQuote] = useState(false);
	const [showSettings, setShowSettings] = useState(false);
	const [pricingBusy, setPricingBusy] = useState(false);
	const [draftBusy, setDraftBusy] = useState(false);
	const queryClient = useQueryClient();

	// AI draft-КП (Move 3): turn the buyer request into a pre-filled draft (copied lines + prices from
	// the seller's offers) in one click — review-and-send instead of building from scratch.
	const handleGenerateDraft = async () => {
		if (!dealId) return;
		setDraftBusy(true);
		try {
			const { prefilled } = await crmApi.generateDraftQuote(dealId);
			await queryClient.invalidateQueries({ queryKey: ['deals'] });
			await queryClient.invalidateQueries({ queryKey: ['quote-items'] });
			toast.success(t('aiDraft.generated', { count: prefilled }));
		} catch (e) {
			// Friendly message per error code (AI_DRAFT_NOT_ENTITLED → «оформите подписку»,
			// NO_REQUEST_LINES, …) via the central apiErrors.* map.
			toast.error(translateApiError(e));
		} finally {
			setDraftBusy(false);
		}
	};
	// UI-only state — deliberately kept OUT of localItems so it never trips hasUnsavedChanges.
	const [expandedRowId, setExpandedRowId] = useState<number | null>(null);
	const [railOpen, setRailOpen] = useState<boolean>(() => {
		try {
			const saved = localStorage.getItem('kp.rail.open');
			if (saved !== null) return saved !== 'false'; // an explicit user toggle always wins
			// Default: open on wide screens, COLLAPSED on laptops (≤~1400px) so the fixed 320px
			// economics rail doesn't squeeze the line table into truncation/overflow (audit A1).
			return typeof window === 'undefined' || window.innerWidth >= 1400;
		} catch { return true; }
	});

	const toggleRail = () => {
		setRailOpen((open) => {
			const next = !open;
			try { localStorage.setItem('kp.rail.open', String(next)); } catch { /* private mode */ }
			return next;
		});
	};
	const toggleRow = (id: number) => setExpandedRowId((current) => (current === id ? null : id));

	useEffect(() => {
		if (quoteItems) {
			setLocalItems(quoteItems);
		}
	}, [quoteItems]);

	const hasUnsavedChanges = useMemo(() => {
		return JSON.stringify(localItems) !== JSON.stringify(quoteItems);
	}, [localItems, quoteItems]);

	const updateItemLocally = (id: number, field: keyof QuoteItem, value: string) => {
		setLocalItems(prev => prev.map(item => {
			if (item.id === id) {
				const cleanValue = value === '' ? "0" : value;
				return { ...item, [field]: cleanValue };
			}
			return item;
		}));
	};

	// The line's COST currency is a code (not a numeric field) — set it verbatim.
	const updateItemCurrency = (id: number, code: string) => {
		setLocalItems(prev => prev.map(item =>
			item.id === id ? { ...item, frozen_currency: code } : item
		));
	};

	const handleSave = async () => {
		try {
			for (const item of localItems) {
				const original = quoteItems.find(oi => oi.id === item.id);
				if (JSON.stringify(item) !== JSON.stringify(original)) {
					await updateMutation.mutateAsync({
						id: item.id,
						data: {
							quantity: item.quantity,
							frozen_base_price: item.frozen_base_price,
							frozen_currency: item.frozen_currency,
							logistics_cost: item.logistics_cost,
							customs_duty: item.customs_duty,
							margin_percent: item.margin_percent,
							discount_percent: item.discount_percent,
							lead_time_days: item.lead_time_days,
							hs_code: item.hs_code,
						}
					});
				}
			}
			if (onSave) onSave();
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	};

	const handleAddItem = async () => {
		if (!newItemName.trim() || !deal?.active_quote) return;
		try {
			await createItemMutation.mutateAsync({
				quote: deal.active_quote.id,
				imported_raw_name: newItemName.trim(),
				quantity: 1,
				frozen_base_price: '0',
				// New lines inherit the КП's default cost currency (fallback UZS).
				frozen_currency: deal.active_quote.cost_currency_default || 'UZS',
			});
			setNewItemName('');
			setShowAddRow(false);
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	};

	const [deleteTarget, setDeleteTarget] = useState<number | null>(null);
	// Manual product attach/re-match for a КП line (the human counterpart to AI-подбор):
	// unmatched lines («Совпадение не найдено») had no way to bind a catalog product.
	const [reassignItemId, setReassignItemId] = useState<number | null>(null);

	const handleDeleteItem = (id: number) => {
		setDeleteTarget(id);
	};

	const confirmDeleteItem = async () => {
		if (deleteTarget == null) return;
		try {
			await deleteItemMutation.mutateAsync(deleteTarget);
			setDeleteTarget(null);
		} catch {
			toast.error(t('errors.operationFailed'));
			setDeleteTarget(null);
		}
	};

	if (itemsLoading || dealLoading) {
		return (
			<Card className="min-h-[200px]">
				<CardContent className="flex flex-col items-center justify-center gap-4 py-12">
					<Skeleton className="h-8 w-full max-w-md" />
					<Skeleton className="h-6 w-full max-w-lg" />
					<Skeleton className="h-6 w-full max-w-lg" />
					<Skeleton className="h-6 w-full max-w-lg" />
					<Skeleton className="h-6 w-3/4 max-w-sm" />
				</CardContent>
			</Card>
		);
	}

	const activeQuote = deal?.active_quote;

	// No active quote → the grid has nothing to operate on. Show a guided
	// empty-state with a primary action that opens the existing КП-creation flow.
	if (!activeQuote) {
		return (
			<>
				<Card className="min-h-[200px]">
					<CardContent className="flex flex-col items-center justify-center gap-3 py-12 text-center">
						<div className="flex size-12 items-center justify-center rounded-full bg-muted">
							<FileText className="size-6 text-muted-foreground" aria-hidden="true" />
						</div>
						<h3 className="text-base font-semibold">{t('quote.empty.title')}</h3>
						<p className="max-w-sm text-sm text-muted-foreground">{t('quote.empty.description')}</p>
						<div className="mt-2 flex flex-wrap items-center justify-center gap-2">
							<Button onClick={handleGenerateDraft} disabled={!dealId || draftBusy}>
								{draftBusy ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" aria-hidden="true" />}
								{t('aiDraft.action')}
							</Button>
							<Button variant="outline" onClick={() => setShowGenerateQuote(true)} disabled={!dealId}>
								<FileText className="size-4" aria-hidden="true" />
								{t('quote.empty.action')}
							</Button>
						</div>
					</CardContent>
				</Card>
				<GenerateQuoteDialog
					dealId={dealId || null}
					open={showGenerateQuote}
					onOpenChange={setShowGenerateQuote}
				/>
			</>
		);
	}

	// Presentation currency (all STORED totals are in UZS); computed columns
	// (Себестоимость / Сумма / итоги) render in it. Defaults to UZS.
	const presentationCurrency = activeQuote?.quote_currency || 'UZS';
	const vatRate = activeQuote?.vat_rate || '12';

	// Pricing-assist (Move 3): pull line costs from the seller's own SupplierOffers and prefill the
	// matched lines — the seller reviews before sending. Speeds time-to-first-КП.
	const handlePricingAssist = async () => {
		if (!activeQuote) return;
		setPricingBusy(true);
		try {
			const { suggestions } = await crmApi.pricingAssist(activeQuote.id);
			if (!suggestions.length) {
				toast.info(t('pricingAssist.none'));
				return;
			}
			for (const s of suggestions) {
				await updateMutation.mutateAsync({
					id: s.item_id,
					// s.currency is string|null (offer may lack a currency); the field is string|undefined,
					// so coerce null→undefined to skip overriding the line currency when none is suggested.
					data: { frozen_base_price: s.base_price, frozen_currency: s.currency ?? undefined, lead_time_days: s.lead_time_days },
				});
			}
			toast.success(t('pricingAssist.applied', { count: suggestions.length }));
		} catch {
			toast.error(t('pricingAssist.error'));
		} finally {
			setPricingBusy(false);
		}
	};

	// Cost-viewer gate: the server already redacts cost fields + returns economics === null
	// for a member without quote.view_cost_margin (G4 redaction). One derived flag drives
	// every cost-bearing column/panel; client-facing numbers (Кол-во, Сумма, итог) are never gated.
	const econ: QuoteEconomics | null = activeQuote.economics ?? null;
	const canViewCost = !!econ;

	// FX rate (сум per 1 unit) for a line cost currency: manual override wins over
	// the frozen snapshot; UZS is always 1. Strings → Decimal for display math.
	const fxSnapshot = activeQuote?.fx_snapshot ?? {};
	const fxManual = activeQuote?.fx_manual ?? {};
	const fxRateFor = (code?: string): string => {
		const ccy = (code || 'UZS').toUpperCase();
		if (ccy === 'UZS') return '1';
		return fxManual[ccy] || fxSnapshot[ccy] || '1';
	};
	// The line's COST shown in the presentation (UZS) currency, for the tooltip.
	const lineCostInPresentation = (item: QuoteItem): string => {
		const native = toDecimal(item.frozen_base_price).plus(toDecimal(item.customs_duty));
		return native.mul(toDecimal(fxRateFor(item.frozen_currency))).toString();
	};
	// Per-line economics derived from stored values (no backend call). The authoritative
	// loss/floor signal stays КП-level (rail); this chip is advisory per-line triage.
	const lineSignal = (item: QuoteItem) => {
		const price = toDecimal(item.final_price_excl_vat).mul(item.quantity || 0);
		const cost = toDecimal(item.landed_cost).mul(item.quantity || 0);
		if (price.lte(0)) return null;
		const marginPct = price.minus(cost).div(price).mul(100).toNumber();
		return {
			marginPct,
			profit: price.minus(cost).toString(),
			belowCost: price.lt(cost),
			belowFloor: !!econ && marginPct < Number(econ.min_margin_percent),
		};
	};
	// КП срок поставки (до N дн.) — backend-computed effective value.
	const effectiveLeadTime = activeQuote?.effective_delivery_lead_time_days ?? 0;

	const handleBasisChange = (basisId: number) => {
		if (!activeQuote) return;
		setBasisMutation.mutate({ id: activeQuote.id, deliveryBasis: basisId });
	};

	// Visible main-row columns (for the detail row colSpan): chevron, name, qty, [base], [margin], sum, delete.
	const mainColCount = canViewCost ? 7 : 5;

	const marginCell = (item: QuoteItem) => {
		if (!canViewCost || !econ) return <span className="text-xs text-muted-foreground">—</span>;
		const sig = lineSignal(item);
		if (!sig) return <span className="text-xs text-muted-foreground">—</span>;
		const tone = marginToneClass(sig.belowCost || sig.belowFloor, sig.marginPct, Number(econ.target_margin_percent));
		return (
			<Tooltip>
				<TooltipTrigger asChild>
					<span className={cn('cursor-help text-xs font-semibold tabular-nums', tone)}>
						{sig.marginPct.toFixed(0)}%
					</span>
				</TooltipTrigger>
				<TooltipContent>
					<div className="flex flex-col gap-0.5">
						<span>{t('quote.economics.landedCost')}: {formatMoney(item.landed_cost, presentationCurrency)}</span>
						<span>{t('quote.lineProfit')}: {formatMoney(sig.profit, presentationCurrency)}</span>
						{/* F6: the per-line margin is derived, not editable — markup is one value for the
						    whole КП. Point the seller at where to change it instead of clicking the cell. */}
						<span className="mt-0.5 text-muted-foreground">{t('quote.marginQuoteLevelHint')}</span>
					</div>
				</TooltipContent>
			</Tooltip>
		);
	};

	// ── Right rail: «Экономика и итоги» — settings summary + economics + billing + actions ──
	const saveButton = (
		<Button variant="outline" size="sm" onClick={handleSave} disabled={updateMutation.isPending}>
			{updateMutation.isPending ? <Loader2 className="size-3 animate-spin" /> : <Save className="size-3" />}
			{t('common.save')}
		</Button>
	);

	const railRow = (label: string, value: React.ReactNode, opts?: { strong?: boolean; tone?: string }) => (
		<div className="flex items-center justify-between gap-3">
			<span className="text-xs text-muted-foreground">{label}</span>
			<span className={cn('tabular-nums', opts?.strong ? 'text-sm font-bold' : 'text-sm font-semibold', opts?.tone)}>
				{value}
			</span>
		</div>
	);

	const railOpenContent = (
		<div id="kp-econ-rail" className="flex h-full w-80 shrink-0 flex-col">
			<div className="flex items-center justify-between border-b px-3 py-2">
				<span className="text-xs font-bold uppercase tracking-wide text-muted-foreground">{t('quote.rail.title')}</span>
				<Button variant="ghost" size="icon-xs" onClick={toggleRail} aria-expanded={true} aria-controls="kp-econ-rail" title={t('quote.rail.collapse')}>
					<PanelRightClose className="size-4" />
				</Button>
			</div>
			<div className="flex flex-1 flex-col gap-4 overflow-y-auto p-3">
				{/* Параметры КП */}
				<div className="flex flex-col gap-2">
					<span className="text-xs font-semibold text-muted-foreground">{t('quote.rail.params')}</span>
					<DeliveryBasisSelect value={activeQuote?.delivery_basis} onChange={handleBasisChange} />
					<div className="flex flex-wrap gap-1.5">
						<Badge variant="outline">{t('quote.vat')} {vatRate}%</Badge>
						<Badge variant="secondary">{presentationCurrency}</Badge>
						{effectiveLeadTime > 0 && (
							<Badge variant="outline">{t('quote.leadTimeBadge', { days: effectiveLeadTime })}</Badge>
						)}
						{Number(activeQuote?.margin_percent ?? 0) > 0 && (
							<Badge variant="outline">{t('quote.marginApplied')} {Number(activeQuote?.margin_percent).toFixed(0)}%</Badge>
						)}
					</div>
					{!activeQuote.frozen_at && (
						<Button variant="outline" size="sm" className="w-full" onClick={() => setShowSettings(true)}>
							<Settings className="size-3" />
							{t('quote.settings.title')}
						</Button>
					)}
				</div>

				{/* Экономика сделки (cost-viewer only) */}
				{econ && (
					<div className="flex flex-col gap-2 rounded-md border p-3">
						<span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('quote.economics.title')}</span>
						{econ.fx_missing && econ.fx_missing.length > 0 && (
							<div className="flex items-center gap-2 rounded-md bg-destructive/10 px-2 py-1.5 text-xs font-medium text-destructive">
								<AlertTriangle className="size-3.5 shrink-0" aria-hidden="true" />
								{t('quote.economics.fxMissing', { currencies: econ.fx_missing.join(', ') })}
							</div>
						)}
						{econ.below_cost ? (
							<div className="flex items-center gap-2 rounded-md bg-destructive/10 px-2 py-1.5 text-xs font-medium text-destructive">
								<AlertTriangle className="size-3.5 shrink-0" aria-hidden="true" />
								{t('quote.economics.belowCost')}
							</div>
						) : econ.below_floor ? (
							<div className="flex items-center gap-2 rounded-md bg-warning/10 px-2 py-1.5 text-xs font-medium text-warning">
								<AlertTriangle className="size-3.5 shrink-0" aria-hidden="true" />
								{t('quote.economics.belowFloor', { floor: Number(econ.min_margin_percent).toFixed(0) })}
							</div>
						) : null}
						{railRow(t('quote.economics.landedCost'), formatMoney(econ.total_landed_cost, presentationCurrency))}
						{railRow(t('quote.economics.grossProfit'), formatMoney(econ.gross_profit, presentationCurrency))}
						{railRow(
							t('quote.economics.grossMargin'),
							<>
								{Number(econ.gross_margin_percent).toFixed(1)}%
								<span className="ml-1 text-xs font-normal text-muted-foreground">
									{t('quote.economics.markupRef', { markup: Number(econ.markup_percent).toFixed(0) })}
								</span>
							</>,
							{ tone: marginToneClass(econ.below_cost || econ.below_floor, Number(econ.gross_margin_percent), Number(econ.target_margin_percent)) },
						)}
						{railRow(t('quote.economics.operatingProfit'), formatMoney(econ.operating_profit, presentationCurrency), { strong: true })}
						<p className="text-xs text-muted-foreground">
							{t('quote.economics.thresholds', { floor: Number(econ.min_margin_percent).toFixed(0), target: Number(econ.target_margin_percent).toFixed(0) })}
						</p>
					</div>
				)}

				{/* Итоги — биллинговая проекция (что платит покупатель) */}
				<div className="flex flex-col gap-2 rounded-md border p-3">
					<span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('quote.rail.totals')}</span>
					{railRow(t('quote.subtotal'), formatMoney(activeQuote?.subtotal_excl_vat, presentationCurrency))}
					{activeQuote?.charges_total != null && (activeQuote.charges?.length ?? 0) > 0 &&
						railRow(t('quote.charges.title'), formatMoney(activeQuote.charges_total, presentationCurrency))}
					{railRow(t('quote.vat'), formatMoney(activeQuote?.vat_amount, presentationCurrency))}
					<Separator />
					{railRow(t('quote.total'), formatMoney(activeQuote?.total_incl_vat, presentationCurrency), { strong: true, tone: 'text-primary' })}
				</div>

				{/* Действия */}
				<div className="mt-auto flex flex-col gap-2 pt-2">
					{saveButton}
					<ExportMenu quoteId={activeQuote.id} />
				</div>
			</div>
		</div>
	);

	const collapsedTone = econ
		? marginToneClass(econ.below_cost || econ.below_floor, Number(econ.gross_margin_percent), Number(econ.target_margin_percent))
		: '';
	const railCollapsedContent = (
		<div className="flex h-full w-14 flex-col items-center gap-3 py-3">
			<Button variant="ghost" size="icon-xs" onClick={toggleRail} aria-expanded={false} aria-controls="kp-econ-rail" title={t('quote.rail.expand')}>
				<PanelRightOpen className="size-4" />
			</Button>
			{/* Keep «Настройки КП» reachable even when the rail is collapsed (no dead-end). */}
			{!activeQuote.frozen_at && (
				<Tooltip>
					<TooltipTrigger asChild>
						<Button variant="ghost" size="icon-xs" onClick={() => setShowSettings(true)} aria-label={t('quote.settings.title')}>
							<Settings className="size-4" />
						</Button>
					</TooltipTrigger>
					<TooltipContent side="left">{t('quote.settings.title')}</TooltipContent>
				</Tooltip>
			)}
			{econ && (
				<Tooltip>
					<TooltipTrigger asChild>
						<span className={cn('cursor-help text-xs font-bold tabular-nums', collapsedTone)}>
							{Number(econ.gross_margin_percent).toFixed(0)}%
						</span>
					</TooltipTrigger>
					<TooltipContent side="left">
						{t('quote.economics.grossMargin')} {Number(econ.gross_margin_percent).toFixed(1)}% · {t('quote.economics.thresholds', { floor: Number(econ.min_margin_percent).toFixed(0), target: Number(econ.target_margin_percent).toFixed(0) })}
					</TooltipContent>
				</Tooltip>
			)}
			{econ && (econ.below_cost || econ.below_floor) && (
				<Tooltip>
					<TooltipTrigger asChild>
						<AlertTriangle className={cn('size-4', econ.below_cost ? 'text-destructive' : 'text-warning')} aria-hidden="true" />
					</TooltipTrigger>
					<TooltipContent side="left">
						{econ.below_cost ? t('quote.economics.belowCost') : t('quote.economics.belowFloor', { floor: Number(econ.min_margin_percent).toFixed(0) })}
					</TooltipContent>
				</Tooltip>
			)}
			<Tooltip>
				<TooltipTrigger asChild>
					<span className="cursor-help text-xs font-bold tabular-nums">{compactNumber(activeQuote?.total_incl_vat, i18n.language)}</span>
				</TooltipTrigger>
				<TooltipContent side="left">{t('quote.total')}: {formatMoney(activeQuote?.total_incl_vat, presentationCurrency)}</TooltipContent>
			</Tooltip>
			<Button variant="ghost" size="icon-xs" onClick={handleSave} disabled={updateMutation.isPending} title={t('common.save')}>
				{updateMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
			</Button>
		</div>
	);

	return (
		<div className="flex flex-col h-full gap-3">
			{/* КП internal approval chain (документооборот) — spans both panes */}
			{activeQuote && <QuoteApprovalChain quote={activeQuote} />}

			{/* Unsaved changes warning */}
			{hasUnsavedChanges && (
				<Alert>
					<AlertTriangle className="size-4" />
					<AlertTitle>{t('quote.unsavedChanges')}</AlertTitle>
					<AlertDescription>{t('quote.unsavedChangesDesc')}</AlertDescription>
				</Alert>
			)}

			{/* Working area: line table (left) + collapsible economics rail (right) */}
			<div className="flex flex-1 min-h-0 gap-3">
				<div className="flex flex-col flex-1 min-w-0 gap-3">
					{/* Slim toolbar — table actions only; КП params + Save/Export live in the rail */}
					<div className="flex items-center justify-between">
						<h2 className="text-sm font-bold">{t('quote.title')}</h2>
						<div className="flex gap-1.5">
							{localItems.some(item => !item.product) && (
								<Button variant="outline" size="sm" onClick={() => setShowAiMatch(true)}>
									<Sparkles className="size-3" />
									{t('aiMatch.button')}
								</Button>
							)}
							{!activeQuote.frozen_at && localItems.some(item => item.product) && (
								<Button variant="outline" size="sm" onClick={handlePricingAssist} disabled={pricingBusy}>
									{pricingBusy ? <Loader2 className="size-3 animate-spin" /> : <Tag className="size-3" />}
									{t('pricingAssist.button')}
								</Button>
							)}
							<Button variant="outline" size="sm" onClick={() => setShowAddRow(!showAddRow)}>
								<Plus className="size-3" />
								{t('common.add')}
							</Button>
						</div>
					</div>

					{/* Data grid */}
					<div className="flex-1 overflow-auto rounded-md border">
						<TooltipProvider>
							<Table className="w-full text-left text-sm">
								<TableHeader className="sticky top-0 z-20 border-b bg-muted">
									<TableRow>
										<TableHead className="w-8 px-1 py-2 sticky left-0 z-30 bg-muted" />
										<TableHead className="px-2 py-2 text-xs font-semibold text-muted-foreground min-w-[200px] sticky left-8 z-30 bg-muted">
											{t('catalog.table.name')}
										</TableHead>
										<TableHead className="px-2 py-2 text-center text-xs font-semibold text-muted-foreground w-20">
											<Tooltip>
												<TooltipTrigger asChild><span className="cursor-help">{t('quote.quantity')}</span></TooltipTrigger>
												<TooltipContent>{t('quote.quantityHelp')}</TooltipContent>
											</Tooltip>
										</TableHead>
										{canViewCost && (
											<TableHead className="px-2 py-2 text-xs font-semibold text-muted-foreground w-52 bg-muted/30">
												<Tooltip>
													<TooltipTrigger asChild><span className="cursor-help">{t('quote.basePrice')}</span></TooltipTrigger>
													<TooltipContent>{t('quote.basePriceHelp')}</TooltipContent>
												</Tooltip>
											</TableHead>
										)}
										{canViewCost && (
											<TableHead className="px-2 py-2 text-center text-xs font-semibold text-muted-foreground w-16">
												{t('quote.marginApplied')}
											</TableHead>
										)}
										<TableHead className="px-2 py-2 text-right text-xs font-semibold text-muted-foreground w-32 pr-4">
											{t('quote.lineTotal')}
										</TableHead>
										<TableHead className="px-2 py-2 w-8" />
									</TableRow>
								</TableHeader>
								<TableBody className="divide-y">
									{localItems.map((item, idx) => {
										const isExpanded = expandedRowId === item.id;
										return (
											<React.Fragment key={item.id}>
												<TableRow className="hover:bg-muted/50 transition-colors group">
													<TableCell className="w-8 px-1 py-1.5 text-center sticky left-0 z-10 bg-background group-hover:bg-muted/50">
														<button
															type="button"
															onClick={(e) => { e.stopPropagation(); toggleRow(item.id); }}
															aria-expanded={isExpanded}
															aria-controls={`kp-line-detail-${item.id}`}
															aria-label={t('quote.lineDetails')}
															className="flex size-5 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
														>
															{isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
														</button>
													</TableCell>
													<TableCell className="px-2 py-1.5 sticky left-8 z-10 bg-background group-hover:bg-muted/50">
														<div className="flex flex-col leading-tight pr-4">
															<div className="flex items-center gap-2">
																{!item.product && (
																	<AlertTriangle className="size-3 text-warning shrink-0" aria-label={t('sourcing.noMatch')} />
																)}
																<span className="text-xs font-mono text-muted-foreground tabular-nums">{idx + 1}.</span>
																<span className="text-sm font-semibold truncate max-w-[260px]" title={item.product_name || item.imported_raw_name || undefined}>
																	{item.product_name || item.imported_raw_name}
																</span>
																{item.product_domain && (
																	<Badge variant="outline" className="text-xs px-1.5 py-0">{item.product_domain}</Badge>
																)}
															</div>
															{item.product ? (
																// Product IS bound: show the supplier (if an offer exists) or the SKU —
																// never «Совпадение не найдено», which contradicts a matched line.
																<span className="text-xs text-muted-foreground mt-0.5 truncate">
																	{item.offer_supplier_name || item.product_sku || '—'}
																</span>
															) : (
																<button
																	type="button"
																	onClick={() => setReassignItemId(item.id)}
																	className="mt-0.5 flex items-center gap-1 text-xs font-medium text-primary hover:underline"
																>
																	<Link2 className="size-3 shrink-0" />
																	{t('quote.attachProduct')}
																</button>
															)}
														</div>
													</TableCell>
													<TableCell className="p-0">
														<Input
															type="number"
															aria-label={t('catalog.table.unit')}
															className="h-8 border-none shadow-none rounded-none text-xs font-semibold text-center focus-visible:ring-1"
															value={item.quantity}
															onChange={(e) => updateItemLocally(item.id, 'quantity', e.target.value)}
														/>
													</TableCell>
													{canViewCost && (
														<TableCell className="p-0 bg-muted/20">
															<div className="flex items-center">
																<Tooltip>
																	<TooltipTrigger asChild>
																		<Input
																			type="number"
																			aria-label={t('quote.basePrice')}
																			className="h-8 border-none shadow-none rounded-none text-xs font-mono text-right pr-2 focus-visible:ring-1"
																			value={item.frozen_base_price}
																			onChange={(e) => updateItemLocally(item.id, 'frozen_base_price', e.target.value)}
																		/>
																	</TooltipTrigger>
																	<TooltipContent>
																		<div className="flex flex-col gap-0.5">
																			<span>{t('quote.costInPresentation', { value: formatMoney(lineCostInPresentation(item), presentationCurrency) })}</span>
																			{(item.frozen_currency || 'UZS').toUpperCase() !== 'UZS' && (
																				<span className="text-muted-foreground">
																					{t('quote.fxRateAt', { rate: fxRateFor(item.frozen_currency), from: (item.frozen_currency || 'UZS').toUpperCase(), to: presentationCurrency })}
																				</span>
																			)}
																		</div>
																	</TooltipContent>
																</Tooltip>
																<Select value={item.frozen_currency || 'UZS'} onValueChange={(code) => updateItemCurrency(item.id, code)}>
																	<SelectTrigger aria-label={t('quote.lineCurrency')} className="h-8 w-20 shrink-0 border-none shadow-none rounded-none text-xs focus:ring-1">
																		<SelectValue />
																	</SelectTrigger>
																	<SelectContent>
																		{currencies.map((ccy) => (<SelectItem key={ccy.id} value={ccy.code}>{ccy.code}</SelectItem>))}
																	</SelectContent>
																</Select>
															</div>
														</TableCell>
													)}
													{canViewCost && (
														<TableCell className="px-2 py-1.5 text-center">{marginCell(item)}</TableCell>
													)}
													<TableCell className="px-2 py-1.5 text-right pr-4">
														<span className="text-sm font-bold tabular-nums">
															{formatMoney(calculateLineTotal(item.final_price_excl_vat, item.quantity), presentationCurrency)}
														</span>
													</TableCell>
													<TableCell className="px-1 py-0.5">
														<Button variant="ghost" size="icon-xs" onClick={() => handleDeleteItem(item.id)} className="text-muted-foreground hover:text-destructive" title={t('common.delete')}>
															<Trash2 className="size-3" />
														</Button>
													</TableCell>
												</TableRow>
												{isExpanded && (
													<TableRow className="bg-muted/30">
														<TableCell colSpan={mainColCount} className="p-0">
															<div id={`kp-line-detail-${item.id}`} className="sticky left-0 flex max-w-full flex-col gap-3 px-4 py-3">
																<span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('quote.lineDetails')}</span>
																<div className="flex flex-wrap gap-4">
																	<label className="flex flex-col gap-1">
																		<span className="text-xs text-muted-foreground">{t('quote.hsCode')}</span>
																		<Input
																			type="text"
																			placeholder={t('quote.hsCode')}
																			className="h-8 w-40 text-xs font-mono"
																			value={item.hs_code || ''}
																			onChange={(e) => updateItemLocally(item.id, 'hs_code', e.target.value)}
																		/>
																	</label>
																	{canViewCost && (
																		<label className="flex flex-col gap-1">
																			<span className="text-xs text-muted-foreground">{t('quote.customsDuty')}</span>
																			<Input
																				type="number"
																				className="h-8 w-32 text-xs font-mono text-right"
																				value={item.customs_duty}
																				onChange={(e) => updateItemLocally(item.id, 'customs_duty', e.target.value)}
																			/>
																		</label>
																	)}
																	<label className="flex flex-col gap-1">
																		<span className="text-xs text-muted-foreground">{t('quote.leadTime')}</span>
																		<Input
																			type="number"
																			min={0}
																			className="h-8 w-24 text-xs text-center"
																			value={item.lead_time_days ?? 0}
																			onChange={(e) => updateItemLocally(item.id, 'lead_time_days', e.target.value)}
																		/>
																	</label>
																	{canViewCost && (
																		<label className="flex flex-col gap-1">
																			<span className="text-xs text-muted-foreground">{t('quote.discountPercent')}</span>
																			<Input
																				type="number"
																				min={0}
																				max={100}
																				className="h-8 w-24 text-xs text-center"
																				value={item.discount_percent ?? 0}
																				onChange={(e) => updateItemLocally(item.id, 'discount_percent', e.target.value)}
																			/>
																		</label>
																	)}
																</div>
																{canViewCost && (
																	<div className="flex flex-wrap gap-6 border-t pt-2 text-xs">
																		<span className="text-muted-foreground">
																			{t('quote.economics.landedCost')}: <span className="font-semibold tabular-nums text-foreground">{formatMoney(item.landed_cost, presentationCurrency)}</span>
																		</span>
																		{(() => {
																			const sig = lineSignal(item);
																			if (!sig) return null;
																			return (
																				<>
																					<span className="text-muted-foreground">
																						{t('quote.lineProfit')}: <span className="font-semibold tabular-nums text-foreground">{formatMoney(sig.profit, presentationCurrency)}</span>
																					</span>
																					<span className="text-muted-foreground">
																						{t('quote.economics.grossMargin')}: <span className={cn('font-semibold tabular-nums', econ ? marginToneClass(sig.belowCost || sig.belowFloor, sig.marginPct, Number(econ.target_margin_percent)) : '')}>{sig.marginPct.toFixed(1)}%</span>
																					</span>
																				</>
																			);
																		})()}
																	</div>
																)}
															</div>
														</TableCell>
													</TableRow>
												)}
											</React.Fragment>
										);
									})}
									{showAddRow && (
										<TableRow className="bg-primary/5">
											<TableCell className="px-2 py-1.5 text-center text-xs text-muted-foreground">+</TableCell>
											<TableCell className="p-1" colSpan={mainColCount - 1}>
												<div className="flex items-center gap-2">
													<Input
														type="text"
														value={newItemName}
														onChange={e => setNewItemName(e.target.value)}
														onKeyDown={e => e.key === 'Enter' && handleAddItem()}
														placeholder={t('quote.addItemPlaceholder')}
														className="h-7 flex-1 text-sm"
														autoFocus
													/>
													<Button size="sm" onClick={handleAddItem} disabled={!newItemName.trim() || createItemMutation.isPending}>
														{t('common.add')}
													</Button>
												</div>
											</TableCell>
										</TableRow>
									)}
								</TableBody>
							</Table>
						</TooltipProvider>
					</div>

					{/* КП-level expense items / discounts (seller-only) — full width under the table */}
					{activeQuote && <QuoteChargesSection quoteId={activeQuote.id} currency={presentationCurrency} />}
				</div>

				{/* Collapsible «Экономика и итоги» rail */}
				<TooltipProvider>
					<aside className={cn('shrink-0 self-stretch overflow-hidden rounded-md border bg-card transition-[width] duration-200 ease-in-out', railOpen ? 'w-80' : 'w-14')}>
						{railOpen ? railOpenContent : railCollapsedContent}
					</aside>
				</TooltipProvider>
			</div>

			<AICatalogMatchDialog open={showAiMatch} onOpenChange={setShowAiMatch} items={localItems} />
			<QuoteSettingsDialog quote={activeQuote} open={showSettings} onOpenChange={setShowSettings} />
			<ReassignProductDialog
				quoteItemId={reassignItemId}
				open={reassignItemId != null}
				onOpenChange={(o) => !o && setReassignItemId(null)}
			/>

			<AlertDialog open={deleteTarget != null} onOpenChange={(o) => !o && setDeleteTarget(null)}>
				<AlertDialogContent>
					<AlertDialogHeader>
						<AlertDialogTitle>{t('quote.deleteItem')}</AlertDialogTitle>
						<AlertDialogDescription>{t('deleteConfirmations.quoteItemDescription')}</AlertDialogDescription>
					</AlertDialogHeader>
					<AlertDialogFooter>
						<AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
						<AlertDialogAction onClick={confirmDeleteItem} disabled={deleteItemMutation.isPending}>
							{t('common.delete')}
						</AlertDialogAction>
					</AlertDialogFooter>
				</AlertDialogContent>
			</AlertDialog>
		</div>
	);
};
