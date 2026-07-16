import React from 'react';
import { useTranslation } from 'react-i18next';
import {
	Loader2, Plus, Sparkles, Settings, Tag, PanelRightClose, PanelRightOpen, Maximize2, Minimize2, ClipboardPaste,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { useQuoteBuilderGrid } from './QuoteBuilderGridContext';

/**
 * The КП builder's document toolbar: row actions on the left (add · Excel-paste · AI-подбор ·
 * pricing-assist) and view controls on the right (settings · rail toggle · focus mode). Extracted
 * verbatim from the former monolithic grid — same gates (frozen КП, unmatched/matched lines), same
 * rail toggle semantics (slide-over below xl, inline collapse ≥xl).
 */
export const BuilderToolbar: React.FC = () => {
	const { t } = useTranslation();
	const {
		activeQuote, draftItems, showAddRow, setShowAddRow, openPasteDialog, setShowAiMatch,
		handlePricingAssist, pricingBusy, setShowSettings, railAsSheet, railOpen, setRailSheetOpen,
		toggleRail, fullscreen, setFullscreen,
	} = useQuoteBuilderGrid();

	return (
		<div className="flex flex-wrap items-center justify-between gap-2">
			<div className="flex flex-wrap gap-1.5">
				<Button variant="outline" size="sm" onClick={() => setShowAddRow(!showAddRow)}>
					<Plus className="size-3" />
					{t('common.add')}
				</Button>
				{!activeQuote.frozen_at && (
					<Button variant="outline" size="sm" onClick={openPasteDialog}>
						<ClipboardPaste className="size-3" />
						{t('quote.paste.button')}
					</Button>
				)}
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
	);
};
