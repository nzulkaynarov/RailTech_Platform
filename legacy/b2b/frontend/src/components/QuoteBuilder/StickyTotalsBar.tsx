import React from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Save, Undo2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatMoney } from '@/utils/decimal';
import { Button } from '@/components/ui/button';

interface StickyTotalsBarProps {
	positionsCount: number;
	/** Cost-viewer gate — hide the margin entirely for a member without quote.view_cost_margin. */
	canViewCost: boolean;
	/** Gross margin % (already a number); only shown when canViewCost. */
	marginPercent?: number;
	/** Semantic tone for the margin figure (below-cost/floor → destructive/warning). */
	marginTone?: string;
	totalInclVat?: string | number | null;
	currency: string;
	hasUnsavedChanges: boolean;
	saving: boolean;
	onSave: () => void;
	/** Revert the last local draft edit (WP-J undo); omit to hide the Undo button. */
	onUndo?: () => void;
	/** Whether there is a draft edit to undo — disables the Undo button when false. */
	canUndo?: boolean;
}

/**
 * Sticky КП footer — the always-visible bottom bar of the builder workspace. Carries the
 * document totals (Позиций · Маржа · Итого с НДС) on the left and the single Save action +
 * unsaved-changes indicator on the right, so the seller never loses sight of the total or
 * the Save button behind a page scroll (fixes «итоги за кнопкой» on ≤768px laptops).
 */
export const StickyTotalsBar: React.FC<StickyTotalsBarProps> = ({
	positionsCount,
	canViewCost,
	marginPercent,
	marginTone,
	totalInclVat,
	currency,
	hasUnsavedChanges,
	saving,
	onSave,
	onUndo,
	canUndo,
}) => {
	const { t } = useTranslation();

	return (
		<div className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-md border bg-card px-3 py-2">
			<div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
				<span className="text-muted-foreground">
					{t('quote.builder.positionsCount', { count: positionsCount })}
				</span>
				{canViewCost && marginPercent != null && (
					<span className="flex items-center gap-1 text-muted-foreground">
						{t('quote.margin')}
						<span className={cn('font-semibold tabular-nums', marginTone)}>{marginPercent.toFixed(1)}%</span>
					</span>
				)}
				<span className="flex items-center gap-1.5">
					<span className="text-xs uppercase tracking-wide text-muted-foreground">{t('quote.total')}</span>
					<span className="text-base font-bold tabular-nums text-primary">
						{formatMoney(totalInclVat, currency)}
					</span>
				</span>
			</div>
			<div className="flex items-center gap-3">
				{hasUnsavedChanges && (
					<span className="text-xs font-medium text-warning">{t('quote.unsavedChanges')}</span>
				)}
				{onUndo && (
					<Button variant="outline" size="sm" onClick={onUndo} disabled={!canUndo}>
						<Undo2 className="size-4" />
						{t('quote.undo')}
					</Button>
				)}
				<Button size="sm" onClick={onSave} disabled={saving}>
					{saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
					{t('common.save')}
				</Button>
			</div>
		</div>
	);
};
