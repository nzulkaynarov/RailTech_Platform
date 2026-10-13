import React from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { Quote, QuoteItem } from '@/api/crmApi';
import {
	AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
	AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { ExcelPasteDialog } from '@/components/QuoteBuilder/ExcelPasteDialog';
import { AICatalogMatchDialog } from '@/components/QuoteBuilder/AICatalogMatchDialog';
import { ImportFileDialog } from '@/components/QuoteBuilder/ImportFileDialog';
import { QuoteSettingsDialog } from '@/components/CRM/QuoteSettingsDialog';
import { ReassignProductDialog } from '@/components/CRM/ReassignProductDialog';
import { QUOTE_ITEMS_BULK_MAX_ROWS } from '@/components/QuoteBuilder/gridConstants';
import type { BulkCreateRow } from '@/components/QuoteBuilder/parseClipboardTable';

export interface GridDialogsProps {
	// ── Excel paste (bulk-create) ───────────────────────────────────────────────────────────────
	pasteOpen: boolean;
	setPasteOpen: Dispatch<SetStateAction<boolean>>;
	pasteText: string;
	pasteRowErrors: Record<number, Record<string, string>>;
	setPasteRowErrors: Dispatch<SetStateAction<Record<number, Record<string, string>>>>;
	pasteSubmitting: boolean;
	onPasteConfirm: (rows: BulkCreateRow[]) => void;

	// ── AI catalog match ────────────────────────────────────────────────────────────────────────
	showAiMatch: boolean;
	setShowAiMatch: Dispatch<SetStateAction<boolean>>;
	draftItems: QuoteItem[];

	// ── Q2: импорт позиций из файла ────────────────────────────────────────────────────────────
	importOpen: boolean;
	setImportOpen: Dispatch<SetStateAction<boolean>>;

	// ── КП settings ─────────────────────────────────────────────────────────────────────────────
	activeQuote: Quote;
	showSettings: boolean;
	setShowSettings: Dispatch<SetStateAction<boolean>>;

	// ── Manual product re-attach ────────────────────────────────────────────────────────────────
	reassignItemId: number | null;
	setReassignItemId: Dispatch<SetStateAction<number | null>>;

	// ── Delete-line confirm ─────────────────────────────────────────────────────────────────────
	deleteTarget: number | null;
	setDeleteTarget: Dispatch<SetStateAction<number | null>>;
	onConfirmDelete: () => void;
	deletePending: boolean;

	// ── Optimistic-lock conflict ────────────────────────────────────────────────────────────────
	conflictOpen: boolean;
	setConflictOpen: Dispatch<SetStateAction<boolean>>;
	conflictIds: number[];
	setConflictIds: Dispatch<SetStateAction<number[]>>;
	clearDirtyAfterSave: (ids: number[]) => void;
	setCellErrors: Dispatch<SetStateAction<Record<string, string>>>;
}

/**
 * All of the КП builder grid's dialogs / modals (волна 3 split — extracted verbatim from the former
 * monolithic `QuoteBuilderGrid`): Excel-paste bulk create, AI catalog match, КП settings, manual
 * product re-attach, the delete-line confirm and the optimistic-lock conflict prompt. A mechanical
 * move — the same state, handlers and props the monolith rendered each pass, no behaviour change.
 */
export const GridDialogs: React.FC<GridDialogsProps> = ({
	pasteOpen, setPasteOpen, pasteText, pasteRowErrors, setPasteRowErrors, pasteSubmitting, onPasteConfirm,
	showAiMatch, setShowAiMatch, draftItems,
	importOpen, setImportOpen,
	activeQuote, showSettings, setShowSettings,
	reassignItemId, setReassignItemId,
	deleteTarget, setDeleteTarget, onConfirmDelete, deletePending,
	conflictOpen, setConflictOpen, conflictIds, setConflictIds, clearDirtyAfterSave, setCellErrors,
}) => {
	const { t } = useTranslation();
	const queryClient = useQueryClient();

	// «Обновить»: consciously drop the local edits on the conflicting rows, then refetch quote-items
	// so the fresh server values re-merge. The seller's stale edits to the conflicting lines are
	// replaced by the colleague's committed values (spec §5.3).
	const handleConflictRefresh = () => {
		const idsToReset = conflictIds;
		clearDirtyAfterSave(idsToReset);
		setCellErrors((previous) => {
			const next = { ...previous };
			for (const key of Object.keys(next)) {
				if (idsToReset.includes(Number(key.split(':')[0]))) delete next[key];
			}
			return next;
		});
		queryClient.invalidateQueries({ queryKey: ['quote-items'] });
		queryClient.invalidateQueries({ queryKey: ['deals'] });
		setConflictOpen(false);
		setConflictIds([]);
		toast.info(t('quote.conflict.refreshed'));
	};

	return (
		<>
			<ExcelPasteDialog
				open={pasteOpen}
				onOpenChange={(open) => {
					setPasteOpen(open);
					if (!open) setPasteRowErrors({});
				}}
				initialText={pasteText}
				maxRows={QUOTE_ITEMS_BULK_MAX_ROWS}
				submitting={pasteSubmitting}
				rowErrors={pasteRowErrors}
				onConfirm={onPasteConfirm}
			/>
			<AICatalogMatchDialog open={showAiMatch} onOpenChange={setShowAiMatch} items={draftItems} />
			<ImportFileDialog open={importOpen} onOpenChange={setImportOpen} quoteId={activeQuote.id} />
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
						<AlertDialogAction onClick={onConfirmDelete} disabled={deletePending}>
							{t('common.delete')}
						</AlertDialogAction>
					</AlertDialogFooter>
				</AlertDialogContent>
			</AlertDialog>

			{/* Optimistic-lock conflict (волна 3): a colleague saved these lines first. This isn't a
			    fixable input error — the seller reloads the fresh values, replacing their stale edits. */}
			<AlertDialog open={conflictOpen} onOpenChange={(o) => !o && setConflictOpen(false)}>
				<AlertDialogContent>
					<AlertDialogHeader>
						<AlertDialogTitle>{t('quote.conflict.title')}</AlertDialogTitle>
						<AlertDialogDescription>{t('quote.conflict.description')}</AlertDialogDescription>
					</AlertDialogHeader>
					<AlertDialogFooter>
						<AlertDialogAction onClick={handleConflictRefresh}>
							{t('quote.conflict.refresh')}
						</AlertDialogAction>
					</AlertDialogFooter>
				</AlertDialogContent>
			</AlertDialog>
		</>
	);
};
