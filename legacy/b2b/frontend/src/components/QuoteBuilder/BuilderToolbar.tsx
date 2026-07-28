import React from 'react';
import { useTranslation } from 'react-i18next';
import {
	Loader2, Plus, Sparkles, Settings, Tag, PanelRightClose, PanelRightOpen, Maximize2, Minimize2, ClipboardPaste, Upload,
	Heading, StickyNote, Search, X, Rows2, Rows3, type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { useQuoteBuilderGrid } from './QuoteBuilderGridContext';

interface ToolbarActionProps {
	icon: LucideIcon;
	iconClassName?: string;
	label: string;
	onClick: () => void;
	disabled?: boolean;
	/** Keep the text label at every width (the primary «Добавить» action). */
	keepLabel?: boolean;
}

/**
 * U2 — a toolbar action whose TEXT collapses below `2xl`, leaving an icon-only button with the
 * label as its tooltip + accessible name.
 *
 * Measured, not guessed: with the economics rail open on a 1440px screen the labelled buttons plus
 * the tabs and the filter overflowed and the toolbar WRAPPED to two lines (74px) — which cost more
 * height than the separate tabs row that merging them was supposed to save. Collapsing the
 * secondary labels keeps the whole toolbar on ONE line at 1440 while a wide monitor still shows
 * full words. Same responsive trick the «Настройки КП» button already used.
 */
const ToolbarAction: React.FC<ToolbarActionProps> = ({ icon: Icon, iconClassName, label, onClick, disabled, keepLabel }) => (
	<Tooltip>
		<TooltipTrigger asChild>
			<Button variant="outline" size="sm" onClick={onClick} disabled={disabled} aria-label={label}>
				<Icon className={cn('size-3', iconClassName)} />
				<span className={keepLabel ? undefined : 'hidden 2xl:inline'}>{label}</span>
			</Button>
		</TooltipTrigger>
		<TooltipContent>{label}</TooltipContent>
	</Tooltip>
);

interface BuilderToolbarProps {
	/**
	 * U2: while ≥1 line is selected the bulk-action strip takes over the LEFT half of this single
	 * toolbar row instead of stacking a second full-width strip above the grid (the Gmail/Airtable
	 * pattern). The tabs and the view controls stay put, so nothing a seller needs mid-quote moves.
	 */
	selectionSlot?: React.ReactNode;
}

/**
 * The КП builder's single document toolbar row (U2). Left→right: the Позиции/Расходы tabs, the row
 * actions (add · section · note · Excel-paste · AI-подбор · pricing-assist) — or, while rows are
 * selected, the bulk-action strip — then «найти в КП» and the view controls (settings · rail toggle ·
 * focus mode).
 *
 * U2: the `TabsList` used to sit on its own line below this toolbar; hosting it here reclaims a full
 * row (~44px incl. the flex gap) of vertical space for actual КП lines. It still renders inside the
 * facade's `<Tabs>` provider, so tab switching is unchanged.
 */
export const BuilderToolbar: React.FC<BuilderToolbarProps> = ({ selectionSlot }) => {
	const { t } = useTranslation();
	const {
		activeTab, activeQuote, draftItems, visibleItems, showAddRow, setShowAddRow, handleAddSection, handleAddNote,
		openPasteDialog, openImportDialog, setShowAiMatch, filterQuery, setFilterQuery, isFiltered,
		handlePricingAssist, pricingBusy, setShowSettings, railAsSheet, railOpen, setRailSheetOpen,
		toggleRail, fullscreen, setFullscreen, gridDensity, toggleGridDensity,
	} = useQuoteBuilderGrid();

	// U7: the button shows the density it will switch TO (the standard toggle-to-other-state pattern
	// this toolbar's rail/focus buttons already use), so its icon + label describe the action.
	const isCompact = gridDensity === 'compact';
	const densityLabel = isCompact ? t('quote.density.comfortable') : t('quote.density.compact');

	const chargesCount = activeQuote.charges?.length ?? 0;

	return (
		<div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1.5">
			<div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
				{/* U2: tabs live in the toolbar row now — one less full-width strip above the grid. */}
				<TabsList className="shrink-0">
					<TabsTrigger value="items">{t('quote.builder.itemsTab')}</TabsTrigger>
					<TabsTrigger value="charges" className="gap-1.5">
						{t('quote.builder.chargesTab')}
						{chargesCount > 0 && (
							<Badge variant="secondary" className="h-4 min-w-4 justify-center px-1 text-xs tabular-nums">
								{chargesCount}
							</Badge>
						)}
					</TabsTrigger>
				</TabsList>

				{/* Item-level actions are meaningless on the Расходы tab (the line list is hidden there),
				    so hide the whole group — and the bulk strip — unless the Позиции tab is active. */}
				{activeTab === 'items' && (selectionSlot ?? (
					<div className="flex flex-wrap gap-1.5">
						<ToolbarAction icon={Plus} label={t('common.add')} onClick={() => setShowAddRow(!showAddRow)} keepLabel />
						{/* S1: секции/заметки — только пока КП не заморожен (как и все правки позиций). */}
						{!activeQuote.frozen_at && (
							<ToolbarAction icon={Heading} label={t('quote.section.add')} onClick={handleAddSection} />
						)}
						{!activeQuote.frozen_at && (
							<ToolbarAction icon={StickyNote} label={t('quote.note.add')} onClick={handleAddNote} />
						)}
						{!activeQuote.frozen_at && (
							<ToolbarAction icon={ClipboardPaste} label={t('quote.paste.button')} onClick={openPasteDialog} />
						)}
						{!activeQuote.frozen_at && (
							<ToolbarAction icon={Upload} label={t('quoteImport.button')} onClick={openImportDialog} />
						)}
						{draftItems.some(item => !item.product) && (
							<ToolbarAction icon={Sparkles} label={t('aiMatch.button')} onClick={() => setShowAiMatch(true)} />
						)}
						{!activeQuote.frozen_at && draftItems.some(item => item.product) && (
							<ToolbarAction
								icon={pricingBusy ? Loader2 : Tag}
								iconClassName={pricingBusy ? 'animate-spin' : undefined}
								label={t('pricingAssist.button')}
								onClick={handlePricingAssist}
								disabled={pricingBusy}
							/>
						)}
					</div>
				))}
			</div>
			<div className="flex items-center gap-1.5">
				{/* U4: «найти в КП» — narrows the line table without touching totals, margin or Save. */}
				<div className="relative">
					<Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
					<Input
						type="search"
						value={filterQuery}
						onChange={(event) => setFilterQuery(event.target.value)}
						onKeyDown={(event) => {
							// Escape clears the filter without leaving the field — Excel/Notion muscle memory.
							if (event.key === 'Escape' && filterQuery) {
								event.preventDefault();
								event.stopPropagation();
								setFilterQuery('');
							}
						}}
						placeholder={t('quote.filter.placeholder')}
						aria-label={t('quote.filter.ariaLabel')}
						className="h-8 w-36 pl-7 pr-7 text-sm sm:w-48"
					/>
					{isFiltered && (
						<Button
							variant="ghost"
							size="icon-xs"
							onClick={() => setFilterQuery('')}
							aria-label={t('quote.filter.clear')}
							className="absolute right-1 top-1/2 size-5 -translate-y-1/2 text-muted-foreground"
						>
							<X className="size-3" />
						</Button>
					)}
				</div>
				{isFiltered && (
					<span className="whitespace-nowrap text-xs text-muted-foreground tabular-nums">
						{t('quote.filter.matchCount', { count: visibleItems.length, total: draftItems.length })}
					</span>
				)}
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
				{/* U7: density toggle — trims the row padding so more КП lines fit (comfortable ↔ compact). */}
				<Tooltip>
					<TooltipTrigger asChild>
						<Button
							variant="outline"
							size="icon-xs"
							className="size-8"
							onClick={toggleGridDensity}
							aria-label={densityLabel}
							aria-pressed={isCompact}
						>
							{isCompact ? <Rows3 className="size-4" /> : <Rows2 className="size-4" />}
						</Button>
					</TooltipTrigger>
					<TooltipContent>{densityLabel}</TooltipContent>
				</Tooltip>
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
	);
};
