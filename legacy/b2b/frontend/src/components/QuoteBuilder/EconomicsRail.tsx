import React from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Settings, PanelRightClose, PanelRightOpen } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatMoney } from '@/utils/decimal';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { DocumentActions } from '@/components/Shared/DocumentActions';
import { deliveryBasisLabelKey } from '@/lib/codes';
import { marginToneClass, compactNumber } from './gridConstants';
import { useQuoteBuilderGrid } from './QuoteBuilderGridContext';

/**
 * «Экономика и итоги» — the КП builder's right rail: params summary, deal economics (cost-viewer
 * only), the live billing totals projection, and the document export. Renders as an inline
 * collapsible `<aside>` ≥xl and a slide-over `<Sheet>` below xl. Extracted verbatim from the former
 * monolithic grid; the live-mirror totals still track unsaved line edits (P0-2).
 */
export const EconomicsRail: React.FC = () => {
	const { t, i18n } = useTranslation();
	const {
		activeQuote, econ, presentationCurrency, vatRate, effectiveLeadTime, mirrorTotals,
		setShowSettings, toggleRail, railAsSheet, railOpen, railSheetOpen,
		setRailSheetOpen,
	} = useQuoteBuilderGrid();

	// Базис поставки живёт в «Настройки КП» (секция «Поставка», S2). Здесь — только read-only
	// chip текущего Incoterm; клик открывает настройки, где базис и правится.
	const basisCode = activeQuote.delivery_basis_data?.code;
	const rawBasisName = activeQuote.delivery_basis_data?.name;
	// Localize the Incoterm description by code; fall back to the RU-only DB name for a
	// basis code this build does not yet know (operator-added lookup row).
	const basisLabelKey = deliveryBasisLabelKey(basisCode);
	const basisName = basisLabelKey ? t(basisLabelKey) : rawBasisName;

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
					{/* Базис поставки — read-only chip; клик открывает «Настройки КП» (S2). Для замороженного
					    КП базис менять нельзя, поэтому chip не кликабелен. */}
					{activeQuote.frozen_at ? (
						<Badge variant="outline" className="w-fit">
							{basisCode ?? t('quote.rail.basisNotSet')}
						</Badge>
					) : (
						<Tooltip>
							<TooltipTrigger asChild>
								<button
									type="button"
									onClick={() => setShowSettings(true)}
									aria-label={t('quote.rail.editBasis')}
									className="w-fit rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
								>
									<Badge variant="outline" className="cursor-pointer gap-1 hover:bg-muted">
										{basisCode ?? t('quote.rail.basisNotSet')}
										<Settings className="size-3 opacity-60" aria-hidden="true" />
									</Badge>
								</button>
							</TooltipTrigger>
							<TooltipContent side="left">
								{basisName ? `${basisName} · ${t('quote.rail.editBasis')}` : t('quote.rail.editBasis')}
							</TooltipContent>
						</Tooltip>
					)}
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
						request={(format) => ({ path: `crm/quotes/${activeQuote.id}/export/`, params: { export_format: format } })}
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

	// «Экономика и итоги»: inline collapsible rail ≥xl, slide-over Sheet below xl.
	if (railAsSheet) {
		return (
			<Sheet open={railSheetOpen} onOpenChange={setRailSheetOpen}>
				<SheetContent side="right" className="w-full p-0 sm:max-w-sm">
					<SheetHeader className="sr-only">
						<SheetTitle>{t('quote.rail.title')}</SheetTitle>
					</SheetHeader>
					<TooltipProvider>{railOpenContent}</TooltipProvider>
				</SheetContent>
			</Sheet>
		);
	}

	return (
		<TooltipProvider>
			<aside className={cn('shrink-0 self-stretch overflow-hidden rounded-md border bg-card transition-[width] duration-200 ease-in-out', railOpen ? 'w-80' : 'w-14')}>
				{railOpen ? railOpenContent : railCollapsedContent}
			</aside>
		</TooltipProvider>
	);
};
