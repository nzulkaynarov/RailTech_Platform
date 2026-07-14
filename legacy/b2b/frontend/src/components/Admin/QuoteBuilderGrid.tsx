import React, { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { QuoteItem, QuoteEconomics, crmApi } from '@/api/crmApi';
import { translateApiError } from '@/lib/apiError';
import {
	Loader2, AlertTriangle, Plus, Trash2, Sparkles, FileText, Settings, Tag,
	ChevronRight, ChevronDown, PanelRightClose, PanelRightOpen, Link2, Maximize2, Minimize2,
} from 'lucide-react';
import { useQuoteItems, useUpdateQuoteItem, useCreateQuoteItem, useDeleteQuoteItem, useDeal, useSetQuoteDeliveryBasis, useBulkUpdateQuoteItems } from '@/hooks/useCRM';
import { useCurrencies } from '@/hooks/useMasterData';
import { useMediaQuery } from '@/hooks/use-mobile';
import { cn } from '@/lib/utils';
import { formatMoney, toDecimal } from '@/utils/decimal';
import { DeliveryBasisSelect } from '@/components/CRM/DeliveryBasisSelect';
import { QuoteChargesSection } from '@/components/CRM/QuoteChargesSection';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip';
import { Separator } from '@/components/ui/separator';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
	Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { StickyTotalsBar } from '@/components/QuoteBuilder/StickyTotalsBar';
import { NumericCell } from '@/components/QuoteBuilder/NumericCell';
import { useQuoteDraft } from '@/components/QuoteBuilder/useQuoteDraft';
import { usePricingMirror } from '@/components/QuoteBuilder/usePricingMirror';
import { parseBulkItemErrors, extractBulkErrorRows, cellErrorKey } from '@/components/QuoteBuilder/bulkErrors';
import { AICatalogMatchDialog } from '@/components/Admin/AICatalogMatchDialog';
import { GenerateQuoteDialog } from '@/components/CRM/GenerateQuoteDialog';
import { QuoteSettingsDialog } from '@/components/CRM/QuoteSettingsDialog';
import { ReassignProductDialog } from '@/components/CRM/ReassignProductDialog';
import { DocumentActions } from '@/components/Shared/DocumentActions';

interface QuoteBuilderGridProps {
	dealId?: number;
	onSave?: () => void;
	/** Lifted so the host page (DealQuotePage) can guard in-app navigation away from unsaved edits. */
	onDirtyChange?: (hasUnsavedChanges: boolean) => void;
}

// E2: sanity upper caps on line quantity/price — mirror backend settings.QUOTE_ITEM_MAX_*
// (санитарный потолок против fat-finger/вставки; backend re-validates and is the hard guard).
const QUOTE_ITEM_MAX_QUANTITY = 1000000;
const QUOTE_ITEM_MAX_UNIT_PRICE = 10000000000;

// Margin health → semantic color, shared by the КП-level rail and the per-line chip.
const marginToneClass = (belowCostOrFloor: boolean, marginPct: number, target: number): string =>
	belowCostOrFloor ? 'text-destructive' : marginPct >= target ? 'text-success' : 'text-warning';

// Compact, locale-aware money for the collapsed rail strip (e.g. «7,8 млн»). Locale follows
// the active i18n language (not hardcoded). Full value is always in the tooltip via formatMoney.
const compactNumber = (value: string | number | null | undefined, locale: string): string =>
	new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value || 0));

export const QuoteBuilderGrid: React.FC<QuoteBuilderGridProps> = ({ dealId: propDealId, onSave, onDirtyChange }) => {
	const { t, i18n } = useTranslation();
	const dealId = propDealId || 0;

	const { data: quoteItems = [], isLoading: itemsLoading } = useQuoteItems({ deal_id: dealId });
	const { data: deal, isLoading: dealLoading } = useDeal(dealId);
	const { data: currencies = [] } = useCurrencies();
	const updateMutation = useUpdateQuoteItem();
	const bulkUpdateMutation = useBulkUpdateQuoteItems();
	const createItemMutation = useCreateQuoteItem();
	const deleteItemMutation = useDeleteQuoteItem();
	const setBasisMutation = useSetQuoteDeliveryBasis();

	// Draft state machine (WP-D): server data merges into non-dirty rows only, so a refetch
	// triggered by settings/charges/basis mutations no longer wipes in-progress line edits.
	const { draftItems, dirtyIds, hasUnsavedChanges, setField, clearDirtyAfterSave } = useQuoteDraft(quoteItems);
	// Per-cell rejection codes from the LAST bulk save (P0-4), keyed `${id}:${field}` → CODE.
	// The batch is transactional, so on rejection nothing is written and dirty state survives;
	// these drive aria-invalid + the localized cell tooltip until the seller re-edits the cell.
	const [cellErrors, setCellErrors] = useState<Record<string, string>>({});
	const [newItemName, setNewItemName] = useState('');
	const [newItemQty, setNewItemQty] = useState<string>('1');
	const [newItemPrice, setNewItemPrice] = useState<string>('0');
	const [showAddRow, setShowAddRow] = useState(false);
	// «Добавить и продолжить»: refocus the name field + keep the row's new position in view.
	const addNameRef = useRef<HTMLInputElement>(null);
	const addRowRef = useRef<HTMLTableRowElement>(null);

	// Edit a line AND drop any stale bulk-save error on that exact cell (so the red ring / tooltip
	// clears the moment the seller starts fixing it). Wraps the draft-machine setField.
	const handleFieldChange = (id: number, field: keyof QuoteItem, value: string | number) => {
		setField(id, field, value);
		const key = cellErrorKey(id, field as string);
		if (cellErrors[key]) {
			setCellErrors((previous) => {
				const next = { ...previous };
				delete next[key];
				return next;
			});
		}
	};

	// Localized message for a rejected cell (or undefined when the cell is clean).
	const cellError = (id: number, field: string): string | undefined => {
		const code = cellErrors[cellErrorKey(id, field)];
		if (!code) return undefined;
		const key = `quote.validation.${code}`;
		const label = t(key);
		return label === key ? code : label; // unlocalized new code → show the raw code
	};

	// Live local pricing mirror (P0-2): for DIRTY rows, re-derive landed_cost / «Сумма» / margin
	// on decimal.js EXACTLY as the backend engine, so an edited price/qty/discount moves the line
	// total and the КП totals immediately — before the save. Clean rows report server values.
	// Called unconditionally (Rules of Hooks) with null-safe inputs off deal?.active_quote — the
	// early returns below (loading / no active quote) must not sit between this and the render.
	const mirrorQuote = deal?.active_quote ?? null;
	const mirrorEcon = mirrorQuote?.economics ?? null;
	const pricingMirror = usePricingMirror({
		draftItems,
		dirtyIds,
		marginPercent: mirrorQuote?.margin_percent,
		vatRate: mirrorQuote?.vat_rate || '12',
		fxSnapshot: mirrorQuote?.fx_snapshot ?? {},
		fxManual: mirrorQuote?.fx_manual ?? {},
		charges: mirrorQuote?.charges ?? [],
		canViewCost: !!mirrorEcon,
		minMarginPercent: mirrorEcon ? Number(mirrorEcon.min_margin_percent) : null,
		serverTotals: {
			subtotalExclVat: mirrorQuote?.subtotal_excl_vat,
			chargesTotal: mirrorQuote?.charges_total,
			vatAmount: mirrorQuote?.vat_amount,
			totalInclVat: mirrorQuote?.total_incl_vat,
			grossMarginPercent: mirrorEcon ? Number(mirrorEcon.gross_margin_percent) : null,
		},
	});
	const mirrorTotals = pricingMirror.totals;
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
	// UI-only state — deliberately kept OUT of draftItems so it never trips hasUnsavedChanges.
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

	// Below Tailwind `xl` (1280px) the economics rail becomes a slide-over Sheet instead of
	// eating horizontal space; ≥xl it stays the inline collapsible <aside>. railSheetOpen is
	// transient (NOT persisted) — localStorage `kp.rail.open` governs only the ≥xl inline collapse.
	const railAsSheet = useMediaQuery('(max-width: 1279px)');
	const [railSheetOpen, setRailSheetOpen] = useState(false);
	// Below 1200px the cost columns (себестоимость + наценка) drop out of the main table so the
	// line grid stays readable; economics stay reachable in each row's expanded detail (see below).
	const isCompact = useMediaQuery('(max-width: 1199px)');

	// Workspace view state (UI-only, kept OUT of draftItems so it never trips hasUnsavedChanges):
	// which document tab is active + focus (fullscreen) mode for the whole grid.
	const [activeTab, setActiveTab] = useState<'items' | 'charges'>('items');
	const [fullscreen, setFullscreen] = useState(false);

	const toggleRow = (id: number) => setExpandedRowId((current) => (current === id ? null : id));

	// Esc exits focus mode (mirrors the ⛶ toggle) — standard editor-workspace affordance.
	useEffect(() => {
		if (!fullscreen) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key !== 'Escape') return;
			// A layered surface (Dialog/AlertDialog/Sheet/Popover — all Radix role="dialog")
			// owns this Escape: it closes itself, focus mode must survive the keystroke.
			if (event.defaultPrevented || document.querySelector('[role="dialog"], [role="alertdialog"]')) return;
			setFullscreen(false);
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, [fullscreen]);

	// Lift the unsaved-changes signal so the host page can guard in-app navigation (Back button).
	useEffect(() => {
		onDirtyChange?.(hasUnsavedChanges);
	}, [hasUnsavedChanges, onDirtyChange]);

	// Browser-level guard: warn before a tab close / reload while there are unsaved edits.
	useEffect(() => {
		if (!hasUnsavedChanges) return;
		const handleBeforeUnload = (event: BeforeUnloadEvent) => {
			event.preventDefault();
			event.returnValue = '';
		};
		window.addEventListener('beforeunload', handleBeforeUnload);
		return () => window.removeEventListener('beforeunload', handleBeforeUnload);
	}, [hasUnsavedChanges]);

	const handleSave = async () => {
		// Only push rows the seller actually edited; the server refetch re-merges the rest.
		const editedItems = draftItems.filter((item) => dirtyIds.has(item.id));
		if (editedItems.length === 0) return;
		const quoteId = deal?.active_quote?.id;
		if (!quoteId) return;
		try {
			// P0-4: ONE transactional request (all-or-nothing) instead of the old per-row
			// `for … await updateQuoteItem` loop that could half-save then blow up mid-way.
			await bulkUpdateMutation.mutateAsync({
				quoteId,
				items: editedItems.map((item) => ({
					id: item.id,
					quantity: item.quantity,
					frozen_base_price: item.frozen_base_price,
					frozen_currency: item.frozen_currency,
					logistics_cost: item.logistics_cost,
					customs_duty: item.customs_duty,
					margin_percent: item.margin_percent,
					discount_percent: item.discount_percent,
					lead_time_days: item.lead_time_days,
					hs_code: item.hs_code,
				})),
			});
			setCellErrors({});
			clearDirtyAfterSave(editedItems.map((item) => item.id));
			toast.success(t('quote.save.success'));
			if (onSave) onSave();
		} catch (error) {
			// Transactional rejection → NOTHING was written; keep the dirty rows and highlight the
			// offending cells by id+field with the machine code (per-row errors from the endpoint).
			const rows = extractBulkErrorRows(error);
			if (rows !== null) {
				const parsed = parseBulkItemErrors(rows);
				setCellErrors(parsed);
				const rowCount = new Set(Object.keys(parsed).map((key) => key.split(':')[0])).size;
				toast.error(t('quote.save.rowsWithErrors', { count: rowCount }));
			} else {
				toast.error(translateApiError(error));
			}
		}
	};

	// «Добавить и продолжить» (spec §5 п.7): add the row, KEEP the add-row open, reset the
	// fields, refocus the name input, and scroll the new row into view — so the seller can
	// enter a whole list without re-opening the add-row each time. Enter also submits.
	const handleAddItem = async () => {
		if (!newItemName.trim() || !deal?.active_quote) return;
		try {
			await createItemMutation.mutateAsync({
				quote: deal.active_quote.id,
				imported_raw_name: newItemName.trim(),
				quantity: Math.max(1, Math.trunc(Number(newItemQty) || 1)),
				frozen_base_price: String(Math.max(0, Number(newItemPrice) || 0)),
				// New lines inherit the КП's default cost currency (fallback UZS).
				frozen_currency: deal.active_quote.cost_currency_default || 'UZS',
			});
			setNewItemName('');
			setNewItemQty('1');
			setNewItemPrice('0');
			// Keep the add-row open and put the cursor back in the name field for the next line.
			requestAnimationFrame(() => {
				addNameRef.current?.focus();
				addRowRef.current?.scrollIntoView?.({ block: 'nearest' });
			});
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
	// Viewport gate layered on top of the cost-viewer gate: on narrow laptops (<1200px) the two
	// cost columns collapse out of the main table. `canViewCost` still guards the expanded detail
	// row, which stays the escape hatch to see/edit economics when the columns are hidden.
	const showCostColumns = canViewCost && !isCompact;

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

	// Per-line economics (advisory chip) — now sourced from the live mirror so a dirty row's
	// margin/loss triage tracks the in-progress edit. Returns null when cost is hidden/unknown.
	const lineSignal = (item: QuoteItem) => {
		const line = pricingMirror.lineFor(item);
		if (line.marginPct == null || line.profit == null) return null;
		return {
			marginPct: line.marginPct,
			profit: line.profit,
			belowCost: line.belowCost,
			belowFloor: line.belowFloor,
		};
	};
	// КП срок поставки (до N дн.) — backend-computed effective value.
	const effectiveLeadTime = activeQuote?.effective_delivery_lead_time_days ?? 0;

	const handleBasisChange = (basisId: number) => {
		if (!activeQuote) return;
		setBasisMutation.mutate({ id: activeQuote.id, deliveryBasis: basisId });
	};

	// Visible main-row columns (for the detail row colSpan): chevron, name, qty, [base], [margin], sum, delete.
	// Gated on showCostColumns (not canViewCost) so colSpan tracks the two cost columns that the
	// <1200px viewport gate hides — a table can't drop columns via Tailwind `hidden` without drift.
	const mainColCount = showCostColumns ? 7 : 5;

	// F6/WP-7: the per-line margin is DERIVED and READ-ONLY — the markup is a single value for
	// the whole КП (quote.margin_percent), never edited per line. Render it muted with NO edit
	// affordance (no colour tone that reads as an actionable field) and a «Настройки КП» hint
	// icon, so the cell can never be mistaken for an editable input.
	const marginCell = (item: QuoteItem) => {
		if (!canViewCost || !econ) return <span className="text-xs text-muted-foreground">—</span>;
		const sig = lineSignal(item);
		if (!sig) return <span className="text-xs text-muted-foreground">—</span>;
		return (
			<Tooltip>
				<TooltipTrigger asChild>
					<span className="inline-flex cursor-help select-none items-center justify-center gap-1 text-xs tabular-nums text-muted-foreground">
						{sig.marginPct.toFixed(0)}%
						<Settings className="size-3 opacity-60" aria-hidden="true" />
					</span>
				</TooltipTrigger>
				<TooltipContent>
					<div className="flex flex-col gap-0.5">
						<span>{t('quote.economics.landedCost')}: {formatMoney(pricingMirror.lineFor(item).landedCost ?? item.landed_cost, presentationCurrency)}</span>
						<span>{t('quote.lineProfit')}: {formatMoney(sig.profit, presentationCurrency)}</span>
						{/* F6: the per-line margin is derived, not editable — markup is one value for the
						    whole КП. Point the seller at «Настройки КП» instead of clicking the cell. */}
						<span className="mt-0.5 font-medium text-foreground">{t('quote.marginQuoteLevelHint')}</span>
					</div>
				</TooltipContent>
			</Tooltip>
		);
	};

	// ── Right rail: «Экономика и итоги» — settings summary + economics + billing + export ──
	// (Save + the unsaved-changes indicator now live in the sticky footer, not the rail.)
	const railRow = (label: string, value: React.ReactNode, opts?: { strong?: boolean; tone?: string }) => (
		<div className="flex items-center justify-between gap-3">
			<span className="text-xs text-muted-foreground">{label}</span>
			<span className={cn('tabular-nums', opts?.strong ? 'text-sm font-bold' : 'text-sm font-semibold', opts?.tone)}>
				{value}
			</span>
		</div>
	);

	const railOpenContent = (
		<div id="kp-econ-rail" className={cn('flex flex-col', railAsSheet ? 'min-h-0 w-full flex-1' : 'h-full w-80 shrink-0')}>
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

				{/* Итоги — биллинговая проекция (что платит покупатель). Живой пересчёт (P0-2): пока
				    есть несохранённые правки строк, показываем предпросмотр итогов из зеркала. */}
				<div className="flex flex-col gap-2 rounded-md border p-3">
					<div className="flex items-center justify-between">
						<span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('quote.rail.totals')}</span>
						{mirrorTotals.isDraft && (
							<span className="text-xs font-medium italic text-warning">
								{mirrorTotals.computable ? t('quote.draftPreview') : t('quote.draftRecalcOnSave')}
							</span>
						)}
					</div>
					{railRow(t('quote.subtotal'), formatMoney(mirrorTotals.subtotalExclVat, presentationCurrency))}
					{activeQuote?.charges_total != null && (activeQuote.charges?.length ?? 0) > 0 &&
						railRow(t('quote.charges.title'), formatMoney(mirrorTotals.chargesTotal, presentationCurrency))}
					{railRow(t('quote.vat'), formatMoney(mirrorTotals.vatAmount, presentationCurrency))}
					<Separator />
					{railRow(t('quote.total'), formatMoney(mirrorTotals.totalInclVat, presentationCurrency), { strong: true, tone: 'text-primary' })}
				</div>

				{/* Экспорт документа (Save lives in the sticky footer) */}
				<div className="mt-auto flex flex-col gap-2 pt-2">
					<DocumentActions
						request={(format) => ({ path: `crm/quotes/${activeQuote.id}/export/`, params: { format } })}
						filenameBase={`RailTech_Quote_${activeQuote.id}`}
						formats={['pdf', 'xlsx', 'csv']}
						variant="default"
					/>
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
					<span className="cursor-help text-xs font-bold tabular-nums">{compactNumber(mirrorTotals.totalInclVat, i18n.language)}</span>
				</TooltipTrigger>
				<TooltipContent side="left">{t('quote.total')}: {formatMoney(mirrorTotals.totalInclVat, presentationCurrency)}</TooltipContent>
			</Tooltip>
		</div>
	);

	return (
		<TooltipProvider>
		<div className={cn(
			'flex flex-col min-h-0 gap-2',
			// Focus (fullscreen) mode: the grid takes over the whole viewport; Esc / ⛶ exits.
			fullscreen ? 'fixed inset-0 z-50 bg-background p-3' : 'h-full',
		)}>
			{/* Document toolbar: row actions (left) + view controls (right) */}
			<div className="flex flex-wrap items-center justify-between gap-2">
				<div className="flex flex-wrap gap-1.5">
					<Button variant="outline" size="sm" onClick={() => setShowAddRow(!showAddRow)}>
						<Plus className="size-3" />
						{t('common.add')}
					</Button>
					{draftItems.some(item => !item.product) && (
						<Button variant="outline" size="sm" onClick={() => setShowAiMatch(true)}>
							<Sparkles className="size-3" />
							{t('aiMatch.button')}
						</Button>
					)}
					{!activeQuote.frozen_at && draftItems.some(item => item.product) && (
						<Button variant="outline" size="sm" onClick={handlePricingAssist} disabled={pricingBusy}>
							{pricingBusy ? <Loader2 className="size-3 animate-spin" /> : <Tag className="size-3" />}
							{t('pricingAssist.button')}
						</Button>
					)}
				</div>
				<div className="flex items-center gap-1.5">
					{/* Single settings entry point (⚙) — editable while the КП is not frozen. */}
					{!activeQuote.frozen_at && (
						<Tooltip>
							<TooltipTrigger asChild>
								<Button variant="outline" size="sm" onClick={() => setShowSettings(true)}>
									<Settings className="size-3" />
									<span className="hidden sm:inline">{t('quote.settings.title')}</span>
								</Button>
							</TooltipTrigger>
							<TooltipContent>{t('quote.settings.title')}</TooltipContent>
						</Tooltip>
					)}
					{/* Rail toggle — opens the slide-over below xl, collapses the inline rail ≥xl. */}
					<Tooltip>
						<TooltipTrigger asChild>
							<Button
								variant="outline"
								size="icon-xs"
								className="size-8"
								onClick={() => (railAsSheet ? setRailSheetOpen(true) : toggleRail())}
								aria-label={!railAsSheet && railOpen ? t('quote.rail.collapse') : t('quote.rail.expand')}
							>
								{!railAsSheet && railOpen ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}
							</Button>
						</TooltipTrigger>
						<TooltipContent>{!railAsSheet && railOpen ? t('quote.rail.collapse') : t('quote.rail.expand')}</TooltipContent>
					</Tooltip>
					{/* Focus mode ⛶ */}
					<Tooltip>
						<TooltipTrigger asChild>
							<Button
								variant="outline"
								size="icon-xs"
								className="size-8"
								onClick={() => setFullscreen((v) => !v)}
								aria-label={fullscreen ? t('quote.builder.fullscreenExit') : t('quote.builder.fullscreenEnter')}
							>
								{fullscreen ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
							</Button>
						</TooltipTrigger>
						<TooltipContent>{fullscreen ? t('quote.builder.fullscreenExit') : t('quote.builder.fullscreenEnter')}</TooltipContent>
					</Tooltip>
				</div>
			</div>

			{/* Working area: tabs (line table + charges) on the left, economics rail on the right */}
			<div className="flex flex-1 min-h-0 gap-3">
				<div className="flex flex-col flex-1 min-w-0 min-h-0">
					<Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'items' | 'charges')} className="flex flex-1 flex-col min-h-0 gap-2">
						<TabsList className="self-start">
							<TabsTrigger value="items">{t('quote.builder.itemsTab')}</TabsTrigger>
							<TabsTrigger value="charges" className="gap-1.5">
								{t('quote.builder.chargesTab')}
								{(activeQuote.charges?.length ?? 0) > 0 && (
									<Badge variant="secondary" className="h-4 min-w-4 justify-center px-1 text-xs tabular-nums">
										{activeQuote.charges?.length}
									</Badge>
								)}
							</TabsTrigger>
						</TabsList>

						<TabsContent value="items" className="flex flex-1 flex-col min-h-0 mt-0 overflow-hidden">
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
										{showCostColumns && (
											<TableHead className="px-2 py-2 text-xs font-semibold text-muted-foreground w-52 bg-muted/30">
												<Tooltip>
													<TooltipTrigger asChild><span className="cursor-help">{t('quote.basePrice')}</span></TooltipTrigger>
													<TooltipContent>{t('quote.basePriceHelp')}</TooltipContent>
												</Tooltip>
											</TableHead>
										)}
										{showCostColumns && (
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
									{draftItems.map((item, idx) => {
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
														<NumericCell
															min={1}
															max={QUOTE_ITEM_MAX_QUANTITY}
															maxToastKey="quote.validation.qtyTooLarge"
															maxFractionDigits={0}
															ariaLabel={t('quote.quantity')}
															className="h-8 border-none shadow-none rounded-none text-xs font-semibold text-center focus-visible:ring-1"
															value={item.quantity}
															invalid={!!cellError(item.id, 'quantity')}
															errorMessage={cellError(item.id, 'quantity')}
															onCommit={(value) => handleFieldChange(item.id, 'quantity', value)}
														/>
													</TableCell>
													{showCostColumns && (
														<TableCell className="p-0 bg-muted/20">
															<div className="flex items-center">
																<Tooltip>
																	<TooltipTrigger asChild>
																		<span className="flex-1">
																			<NumericCell
																				min={0}
																				max={QUOTE_ITEM_MAX_UNIT_PRICE}
																				maxToastKey="quote.validation.priceTooLarge"
																				ariaLabel={t('quote.basePrice')}
																				className="h-8 w-full border-none shadow-none rounded-none text-xs font-mono text-right pr-2 focus-visible:ring-1"
																				value={item.frozen_base_price}
																				invalid={!!cellError(item.id, 'frozen_base_price')}
																				errorMessage={cellError(item.id, 'frozen_base_price')}
																				onCommit={(value) => handleFieldChange(item.id, 'frozen_base_price', value)}
																			/>
																		</span>
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
																<Select value={item.frozen_currency || 'UZS'} onValueChange={(code) => handleFieldChange(item.id, 'frozen_currency', code)}>
																	<SelectTrigger
																		aria-label={t('quote.lineCurrency')}
																		aria-invalid={!!cellError(item.id, 'frozen_currency') || undefined}
																		title={cellError(item.id, 'frozen_currency')}
																		className={cn('h-8 w-20 shrink-0 border-none shadow-none rounded-none text-xs focus:ring-1', cellError(item.id, 'frozen_currency') && 'border-destructive ring-1 ring-destructive')}
																	>
																		<SelectValue />
																	</SelectTrigger>
																	<SelectContent>
																		{currencies.map((ccy) => (<SelectItem key={ccy.id} value={ccy.code}>{ccy.code}</SelectItem>))}
																	</SelectContent>
																</Select>
															</div>
														</TableCell>
													)}
													{showCostColumns && (
														<TableCell className="px-2 py-1.5 text-center">{marginCell(item)}</TableCell>
													)}
													<TableCell className="px-2 py-1.5 text-right pr-4">
														{(() => {
															// Live «Сумма» from the mirror: for a dirty row this is the preview
															// (marked «черновик» in italics); a needsServerRecalc row shows the
															// server total with a «пересчёт после сохранения» hint (honest, not faked).
															const line = pricingMirror.lineFor(item);
															const money = formatMoney(line.lineTotal, presentationCurrency);
															if (line.needsServerRecalc) {
																return (
																	<Tooltip>
																		<TooltipTrigger asChild>
																			<span className="cursor-help text-sm font-bold italic tabular-nums text-muted-foreground">{money} ~</span>
																		</TooltipTrigger>
																		<TooltipContent>{t('quote.draftRecalcOnSave')}</TooltipContent>
																	</Tooltip>
																);
															}
															return (
																<span
																	className={cn('text-sm font-bold tabular-nums', line.isDraft && 'italic text-primary')}
																	title={line.isDraft ? t('quote.draftPreview') : undefined}
																>
																	{line.isDraft ? '≈ ' : ''}{money}
																</span>
															);
														})()}
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
																			aria-invalid={!!cellError(item.id, 'hs_code') || undefined}
																			title={cellError(item.id, 'hs_code')}
																			className={cn('h-8 w-40 text-xs font-mono', cellError(item.id, 'hs_code') && 'border-destructive ring-1 ring-destructive')}
																			value={item.hs_code || ''}
																			onChange={(e) => handleFieldChange(item.id, 'hs_code', e.target.value)}
																		/>
																	</label>
																	{canViewCost && (
																		<label className="flex flex-col gap-1">
																			<span className="text-xs text-muted-foreground">{t('quote.customsDuty')}</span>
																			<NumericCell
																				min={0}
																				max={QUOTE_ITEM_MAX_UNIT_PRICE}
																				maxToastKey="quote.validation.priceTooLarge"
																				ariaLabel={t('quote.customsDuty')}
																				className="h-8 w-32 text-xs font-mono text-right"
																				value={item.customs_duty}
																				invalid={!!cellError(item.id, 'customs_duty')}
																				errorMessage={cellError(item.id, 'customs_duty')}
																				onCommit={(value) => handleFieldChange(item.id, 'customs_duty', value)}
																			/>
																		</label>
																	)}
																	<label className="flex flex-col gap-1">
																		<span className="text-xs text-muted-foreground">{t('quote.leadTime')}</span>
																		<NumericCell
																			min={0}
																			maxFractionDigits={0}
																			ariaLabel={t('quote.leadTime')}
																			className="h-8 w-24 text-xs text-center"
																			value={item.lead_time_days ?? 0}
																			invalid={!!cellError(item.id, 'lead_time_days')}
																			errorMessage={cellError(item.id, 'lead_time_days')}
																			onCommit={(value) => handleFieldChange(item.id, 'lead_time_days', value)}
																		/>
																	</label>
																	{canViewCost && (
																		<label className="flex flex-col gap-1">
																			<span className="text-xs text-muted-foreground">{t('quote.discountPercent')}</span>
																			<NumericCell
																				min={0}
																				max={100}
																				ariaLabel={t('quote.discountPercent')}
																				className="h-8 w-24 text-xs text-center"
																				value={item.discount_percent ?? 0}
																				invalid={!!cellError(item.id, 'discount_percent')}
																				errorMessage={cellError(item.id, 'discount_percent')}
																				onCommit={(value) => handleFieldChange(item.id, 'discount_percent', value)}
																			/>
																		</label>
																	)}
																</div>
																{canViewCost && (
																	<div className="flex flex-wrap gap-6 border-t pt-2 text-xs">
																		<span className="text-muted-foreground">
																			{t('quote.economics.landedCost')}: <span className="font-semibold tabular-nums text-foreground">{formatMoney(pricingMirror.lineFor(item).landedCost ?? item.landed_cost, presentationCurrency)}</span>
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
										<TableRow ref={addRowRef} className="bg-primary/5">
											<TableCell className="px-2 py-1.5 text-center text-xs text-muted-foreground">+</TableCell>
											<TableCell className="p-1" colSpan={mainColCount - 1}>
												{/* Быстрый ввод (spec §5 п.7): наименование + кол-во + базовая цена. Enter =
												    «добавить и продолжить» (строка остаётся, фокус возвращается в наименование);
												    Escape закрывает строку добавления. */}
												<div
													className="flex flex-wrap items-center gap-2"
													onKeyDown={(event) => {
														if (event.key === 'Enter') {
															event.preventDefault();
															handleAddItem();
														} else if (event.key === 'Escape') {
															event.preventDefault();
															setShowAddRow(false);
														}
													}}
												>
													<Input
														ref={addNameRef}
														type="text"
														value={newItemName}
														onChange={e => setNewItemName(e.target.value)}
														placeholder={t('quote.addItemPlaceholder')}
														aria-label={t('catalog.table.name')}
														className="h-7 min-w-[200px] flex-1 text-sm"
														autoFocus
													/>
													<NumericCell
														min={1}
														max={QUOTE_ITEM_MAX_QUANTITY}
														maxToastKey="quote.validation.qtyTooLarge"
														maxFractionDigits={0}
														ariaLabel={t('quote.quantity')}
														className="h-7 w-20 text-sm text-center"
														value={newItemQty}
														onCommit={setNewItemQty}
													/>
													<NumericCell
														min={0}
														max={QUOTE_ITEM_MAX_UNIT_PRICE}
														maxToastKey="quote.validation.priceTooLarge"
														ariaLabel={t('quote.basePrice')}
														className="h-7 w-32 text-sm font-mono text-right"
														value={newItemPrice}
														onCommit={setNewItemPrice}
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

					</TabsContent>

						{/* КП-level expense items / discounts (seller-only) — its own tab so it never
						    steals vertical budget from the line table (audit: «скролл в скролле»). */}
						<TabsContent value="charges" className="flex-1 min-h-0 overflow-auto mt-0">
							{activeQuote && <QuoteChargesSection quoteId={activeQuote.id} currency={presentationCurrency} />}
						</TabsContent>
					</Tabs>
				</div>

				{/* «Экономика и итоги»: inline collapsible rail ≥xl, slide-over Sheet below xl */}
				{railAsSheet ? (
					<Sheet open={railSheetOpen} onOpenChange={setRailSheetOpen}>
						<SheetContent side="right" className="w-full p-0 sm:max-w-sm">
							<SheetHeader className="sr-only">
								<SheetTitle>{t('quote.rail.title')}</SheetTitle>
							</SheetHeader>
							<TooltipProvider>{railOpenContent}</TooltipProvider>
						</SheetContent>
					</Sheet>
				) : (
					<TooltipProvider>
						<aside className={cn('shrink-0 self-stretch overflow-hidden rounded-md border bg-card transition-[width] duration-200 ease-in-out', railOpen ? 'w-80' : 'w-14')}>
							{railOpen ? railOpenContent : railCollapsedContent}
						</aside>
					</TooltipProvider>
				)}
			</div>

			{/* Sticky totals footer — always in view (fixes «итоги за кнопкой» on ≤768px laptops).
			    Total + margin come from the live mirror so they track unsaved line edits (P0-2). */}
			<StickyTotalsBar
				positionsCount={draftItems.length}
				canViewCost={canViewCost}
				marginPercent={mirrorTotals.grossMarginPercent ?? (econ ? Number(econ.gross_margin_percent) : undefined)}
				marginTone={econ
					? marginToneClass(
						econ.below_cost || econ.below_floor,
						mirrorTotals.grossMarginPercent ?? Number(econ.gross_margin_percent),
						Number(econ.target_margin_percent),
					)
					: undefined}
				totalInclVat={mirrorTotals.totalInclVat}
				currency={presentationCurrency}
				hasUnsavedChanges={hasUnsavedChanges}
				saving={bulkUpdateMutation.isPending}
				onSave={handleSave}
			/>

			<AICatalogMatchDialog open={showAiMatch} onOpenChange={setShowAiMatch} items={draftItems} />
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
		</TooltipProvider>
	);
};
