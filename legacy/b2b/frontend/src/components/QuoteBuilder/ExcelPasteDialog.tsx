import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, AlertTriangle } from 'lucide-react';

import {
	Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';
import {
	parseClipboardTable, toBulkCreateRows, type ColumnRole, type BulkCreateRow,
} from '@/components/QuoteBuilder/parseClipboardTable';

interface ExcelPasteDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	/** Raw clipboard text captured by the toolbar button or the grid `onPaste`. */
	initialText: string;
	/** Max lines the bulk endpoint accepts — rows beyond this are dropped with a warning. */
	maxRows: number;
	/** True while the bulk-create request is in flight. */
	submitting: boolean;
	/** Per-row rejection codes from the LAST bulk-create attempt: `index` → (`field` → CODE). */
	rowErrors: Record<number, Record<string, string>>;
	onConfirm: (rows: BulkCreateRow[]) => void;
}

/** Map a column's role to the bulk-create field its errors are reported under. */
const roleToField: Record<ColumnRole, string | null> = {
	name: 'imported_raw_name',
	quantity: 'quantity',
	price: 'frozen_base_price',
	ignore: null,
};

const COLUMN_ROLES: ColumnRole[] = ['name', 'quantity', 'price', 'ignore'];

/**
 * Excel-paste preview + confirm dialog (spec §5 п.12 — differentiator #1). Shows the parsed
 * clipboard table with an editable role per column (defaulted by heuristic), a recognised-rows
 * counter, an over-limit warning, and — after a rejected bulk-create — inline per-cell highlights
 * that keep the dialog open so the seller can fix or drop the offending rows.
 */
export const ExcelPasteDialog: React.FC<ExcelPasteDialogProps> = ({
	open, onOpenChange, initialText, maxRows, submitting, rowErrors, onConfirm,
}) => {
	const { t } = useTranslation();
	const [text, setText] = useState(initialText);
	const [roles, setRoles] = useState<ColumnRole[]>([]);

	// Reset the editable source whenever the dialog (re)opens with fresh clipboard text.
	useEffect(() => {
		if (open) setText(initialText);
	}, [open, initialText]);

	// Re-parse on every source change; identity is stable while `text` is unchanged.
	const table = useMemo(() => parseClipboardTable(text), [text]);

	// Any source change re-derives the heuristic roles; a lone role-select change leaves `text`
	// untouched, so this effect does not fire and the manual override survives.
	useEffect(() => {
		setRoles(table.roles);
	}, [table]);

	const previewRows = useMemo(() => table.rows.slice(0, maxRows), [table.rows, maxRows]);
	const totalRows = table.rows.length;
	const truncated = totalRows > maxRows;
	const hasNameColumn = roles.includes('name');
	const hasRowErrors = Object.keys(rowErrors).length > 0;

	const payloadRows = useMemo(() => toBulkCreateRows(table, roles, maxRows), [table, roles, maxRows]);
	const canConfirm = payloadRows.length > 0 && hasNameColumn && !submitting;

	const setColumnRole = (columnIndex: number, role: ColumnRole) => {
		setRoles((current) => {
			const next = [...current];
			next[columnIndex] = role;
			return next;
		});
	};

	const roleLabel = (role: ColumnRole): string => t(`quote.paste.role.${role}`);

	// Localize a per-cell rejection code the same way the grid does (quote.validation.<CODE>),
	// falling back to the raw code when a new backend code is not yet localized.
	const codeLabel = (code: string): string => {
		const key = `quote.validation.${code}`;
		const label = t(key);
		return label === key ? code : label;
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="flex max-h-[85vh] flex-col gap-4 sm:max-w-4xl">
				<DialogHeader>
					<DialogTitle>{t('quote.paste.title')}</DialogTitle>
					<DialogDescription>{t('quote.paste.description')}</DialogDescription>
				</DialogHeader>

				<div className="flex flex-col gap-1.5">
					<label htmlFor="excel-paste-source" className="text-xs font-medium text-muted-foreground">
						{t('quote.paste.sourceLabel')}
					</label>
					<Textarea
						id="excel-paste-source"
						value={text}
						onChange={(event) => setText(event.target.value)}
						placeholder={t('quote.paste.sourcePlaceholder')}
						rows={3}
						className="font-mono text-xs"
					/>
				</div>

				{table.columnCount === 0 ? (
					<p className="rounded-md border border-dashed py-6 text-center text-sm text-muted-foreground">
						{t('quote.paste.empty')}
					</p>
				) : (
					<div className="flex min-h-0 flex-1 flex-col gap-2">
						<div className="flex flex-wrap items-center gap-2 text-sm">
							<span className="font-medium">{t('quote.paste.rowsRecognized', { count: totalRows })}</span>
							{truncated && (
								<span className="inline-flex items-center gap-1 text-warning">
									<AlertTriangle className="size-3.5" aria-hidden="true" />
									{t('quote.paste.truncated', { max: maxRows, total: totalRows })}
								</span>
							)}
							{!hasNameColumn && (
								<span className="inline-flex items-center gap-1 text-destructive">
									<AlertTriangle className="size-3.5" aria-hidden="true" />
									{t('quote.paste.noNameColumn')}
								</span>
							)}
							{hasRowErrors && (
								<span className="inline-flex items-center gap-1 text-destructive">
									<AlertTriangle className="size-3.5" aria-hidden="true" />
									{t('quote.paste.hasErrors')}
								</span>
							)}
						</div>

						<div className="min-h-0 flex-1 overflow-auto rounded-md border">
							<Table className="text-sm">
								<TableHeader className="sticky top-0 z-10 bg-muted">
									<TableRow>
										<TableHead className="w-10 px-2 text-center text-xs text-muted-foreground">
											{t('quote.paste.rowNumber')}
										</TableHead>
										{Array.from({ length: table.columnCount }).map((_unused, columnIndex) => (
											<TableHead key={columnIndex} className="px-2 py-1.5">
												<Select
													value={roles[columnIndex] ?? 'ignore'}
													onValueChange={(value) => setColumnRole(columnIndex, value as ColumnRole)}
												>
													<SelectTrigger size="sm" className="h-7 min-w-[120px] text-xs" aria-label={t('quote.paste.columnRole', { index: columnIndex + 1 })}>
														<SelectValue />
													</SelectTrigger>
													<SelectContent>
														{COLUMN_ROLES.map((role) => (
															<SelectItem key={role} value={role} className="text-xs">
																{roleLabel(role)}
															</SelectItem>
														))}
													</SelectContent>
												</Select>
											</TableHead>
										))}
									</TableRow>
								</TableHeader>
								<TableBody>
									{previewRows.map((cells, rowIndex) => {
										const errorFields = rowErrors[rowIndex];
										const rowHasError = !!errorFields && Object.keys(errorFields).length > 0;
										return (
											<TableRow
												key={rowIndex}
												data-row-index={rowIndex}
												aria-invalid={rowHasError || undefined}
												className={cn(rowHasError && 'bg-destructive/10')}
											>
												<TableCell className="px-2 text-center text-xs tabular-nums text-muted-foreground">
													{rowIndex + 1}
												</TableCell>
												{cells.map((cell, columnIndex) => {
													const field = roleToField[roles[columnIndex] ?? 'ignore'];
													const code = field ? errorFields?.[field] : undefined;
													return (
														<TableCell
															key={columnIndex}
															aria-invalid={code ? true : undefined}
															title={code ? codeLabel(code) : undefined}
															className={cn(
																'px-2 py-1 text-sm',
																roles[columnIndex] === 'ignore' && 'text-muted-foreground',
																code && 'font-medium text-destructive',
															)}
														>
															{cell || <span className="text-muted-foreground">—</span>}
															{code && (
																<span className="block text-xs font-normal text-destructive">
																	{codeLabel(code)}
																</span>
															)}
														</TableCell>
													);
												})}
											</TableRow>
										);
									})}
								</TableBody>
							</Table>
						</div>
					</div>
				)}

				<DialogFooter>
					<Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
						{t('common.cancel')}
					</Button>
					<Button onClick={() => onConfirm(payloadRows)} disabled={!canConfirm}>
						{submitting && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
						{t('quote.paste.confirm', { count: payloadRows.length })}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
};
