/**
 * Excel-paste parser (spec §5 п.12 — wave 2, differentiator #1).
 *
 * Sellers receive their заявки as Excel lists. This pure module turns a tab-separated
 * clipboard payload (Excel / Google Sheets → TSV) into КП line rows the bulk-create
 * endpoint accepts. It is deliberately UI-free and side-effect-free so it can be unit
 * tested in isolation and reused by both the toolbar button and the grid `onPaste`.
 */

export type ColumnRole = 'name' | 'quantity' | 'price' | 'ignore';

/** A cleaned tabular parse: a rectangular string grid + the heuristic role per column. */
export interface ParsedTable {
	/** Non-empty rows, each padded to `columnCount` cells; every cell already trimmed. */
	rows: string[][];
	columnCount: number;
	/** Heuristic default role per column (index-aligned with each row's cells). */
	roles: ColumnRole[];
}

/** A single bulk-create payload row — mirrors `crm.services.quotes._BULK_CREATE_WRITABLE_FIELDS`.
 *  A type ALIAS, not an `interface`, so it is structurally assignable to the bulk-create endpoint's
 *  `Record<string, unknown>` row contract and the call site needs no cast (DT6). */
export type BulkCreateRow = {
	imported_raw_name: string;
	quantity?: number;
	frozen_base_price?: string;
};

/**
 * Normalise a locale-formatted numeric cell to a plain machine string, or `null` when the cell
 * is not a number. Handles the RU convention (decimal comma) and thousands separators (regular
 * space, NBSP, narrow NBSP) that Excel/Sheets emit: «1 234,50» → "1234.50".
 */
export function normalizeNumericString(raw: string | null | undefined): string | null {
	if (raw == null) return null;
	let value = String(raw).trim();
	if (!value) return null;
	// Strip thousands separators. \s already covers the regular space plus the NBSP and
	// narrow-NBSP characters Excel/Sheets emit, so a single \s class suffices.
	value = value.replace(/\s/g, '');
	const hasComma = value.includes(',');
	const hasDot = value.includes('.');
	if (hasComma && hasDot) {
		// Both present — the LAST separator is the decimal one, the other groups thousands.
		if (value.lastIndexOf(',') > value.lastIndexOf('.')) {
			value = value.replace(/\./g, '').replace(',', '.');
		} else {
			value = value.replace(/,/g, '');
		}
	} else if (hasComma) {
		// A lone comma is the decimal separator; multiple commas group thousands (1,234,567).
		const commaCount = (value.match(/,/g) || []).length;
		value = commaCount > 1 ? value.replace(/,/g, '') : value.replace(',', '.');
	}
	// Reject anything that is not a clean decimal after normalisation.
	if (!/^-?\d*\.?\d+$/.test(value)) return null;
	return value;
}

/** True when the cell parses as a number (used to type-detect columns). */
const isNumericCell = (raw: string): boolean => normalizeNumericString(raw) !== null;

/**
 * Heuristic column-role assignment: the first predominantly-textual column is the name; the
 * remaining predominantly-numeric columns become quantity then price, in left-to-right order.
 * This is only a DEFAULT — the preview dialog lets the seller override every column.
 */
export function detectColumnRoles(rows: string[][], columnCount: number): ColumnRole[] {
	if (columnCount <= 0) return [];
	if (columnCount === 1) return ['name'];

	const numericFraction: number[] = [];
	for (let col = 0; col < columnCount; col += 1) {
		let filled = 0;
		let numeric = 0;
		for (const row of rows) {
			const cell = row[col] ?? '';
			if (cell === '') continue;
			filled += 1;
			if (isNumericCell(cell)) numeric += 1;
		}
		numericFraction[col] = filled === 0 ? 0 : numeric / filled;
	}

	const roles: ColumnRole[] = new Array(columnCount).fill('ignore');
	// Name = first column that is NOT mostly numeric; fall back to the first column.
	let nameCol = numericFraction.findIndex((fraction) => fraction < 0.5);
	if (nameCol === -1) nameCol = 0;
	roles[nameCol] = 'name';
	// The remaining mostly-numeric columns become quantity then price.
	const numericCols: number[] = [];
	for (let col = 0; col < columnCount; col += 1) {
		if (col !== nameCol && numericFraction[col] >= 0.5) numericCols.push(col);
	}
	if (numericCols[0] != null) roles[numericCols[0]] = 'quantity';
	if (numericCols[1] != null) roles[numericCols[1]] = 'price';
	return roles;
}

/**
 * Parse a clipboard payload into a rectangular table. Splits on CRLF/CR/LF, then each line on
 * tabs; trims every cell; drops fully-empty rows and fully-empty columns. Returns an empty table
 * (`rows: []`) when there is nothing tabular to import.
 */
export function parseClipboardTable(text: string | null | undefined): ParsedTable {
	if (!text || !text.trim()) return { rows: [], columnCount: 0, roles: [] };

	const rawRows = text
		.split(/\r\n|\r|\n/)
		.map((line) => line.split('\t').map((cell) => cell.trim()))
		// Drop rows where every cell is blank (trailing newlines, blank separator lines).
		.filter((cells) => cells.some((cell) => cell !== ''));

	if (rawRows.length === 0) return { rows: [], columnCount: 0, roles: [] };

	const width = Math.max(...rawRows.map((cells) => cells.length));
	// Pad every row to a rectangle so column indices are stable.
	const padded = rawRows.map((cells) => {
		const next = cells.slice(0, width);
		while (next.length < width) next.push('');
		return next;
	});

	// Drop columns that are empty in every row (Excel often appends a trailing tab).
	const keptCols: number[] = [];
	for (let col = 0; col < width; col += 1) {
		if (padded.some((row) => row[col] !== '')) keptCols.push(col);
	}
	const rows = padded.map((row) => keptCols.map((col) => row[col]));
	const columnCount = keptCols.length;
	const roles = detectColumnRoles(rows, columnCount);
	return { rows, columnCount, roles };
}

/**
 * Build the bulk-create payload from a parsed table + the (possibly overridden) column roles.
 * Rows beyond `maxRows` are dropped (the endpoint rejects batches above the same cap). Only the
 * name is required; quantity/price are forwarded only when their column maps and the cell is a
 * number — a missing quantity/price falls back to the server defaults (qty=1, base 0). Empty-name
 * rows are KEPT so their index still lines up with the server's per-row error report.
 */
export function toBulkCreateRows(table: ParsedTable, roles: ColumnRole[], maxRows: number): BulkCreateRow[] {
	const nameIdx = roles.indexOf('name');
	const qtyIdx = roles.indexOf('quantity');
	const priceIdx = roles.indexOf('price');
	const limited = maxRows > 0 ? table.rows.slice(0, maxRows) : table.rows;

	return limited.map((cells) => {
		const row: BulkCreateRow = {
			imported_raw_name: nameIdx >= 0 ? (cells[nameIdx] ?? '').trim() : '',
		};
		if (qtyIdx >= 0) {
			const normalized = normalizeNumericString(cells[qtyIdx]);
			if (normalized != null) row.quantity = Math.trunc(Number(normalized));
		}
		if (priceIdx >= 0) {
			const normalized = normalizeNumericString(cells[priceIdx]);
			if (normalized != null) row.frozen_base_price = normalized;
		}
		return row;
	});
}

/**
 * Decide whether a native paste should be hijacked into the Excel-paste dialog. A single-cell
 * paste (no tabs, single line) into an editable input is left to the browser so normal in-cell
 * editing keeps working; anything multi-line or tab-separated that yields ≥1 parseable row is
 * intercepted, regardless of the paste target.
 */
export function shouldInterceptClipboardPaste(text: string, targetIsEditable: boolean): boolean {
	if (!text) return false;
	const lines = text.split(/\r\n|\r|\n/).filter((line) => line.trim() !== '');
	const isTabular = text.includes('\t') || lines.length > 1;
	if (targetIsEditable && !isTabular) return false;
	return parseClipboardTable(text).rows.length > 0;
}
