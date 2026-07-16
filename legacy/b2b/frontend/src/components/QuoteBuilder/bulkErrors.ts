/**
 * Bulk-save per-row error parsing (WP-F / spec §2 P0-4).
 *
 * The bulk endpoint answers a rejected batch with the machine-coded shape
 *   { detail: "QUOTE_ITEMS_BULK_INVALID", rows: [ { id, index, errors: { field: [CODE] } } ] }
 * (crm/services/quotes.bulk_update_quote_items). The whole batch is transactional —
 * NOTHING is written — so the grid keeps its dirty state and highlights the offending
 * cells. This helper flattens `rows` into a flat `${id}:${field}` → CODE map the grid
 * reads to drive `aria-invalid` + the localized cell tooltip.
 */

export interface BulkErrorRow {
	id?: number | string | null;
	index?: number;
	errors?: Record<string, unknown>;
}

/** Key for a single offending cell — the row id and the field name. */
export const cellErrorKey = (id: number, field: string): string => `${id}:${field}`;

/**
 * Flatten the bulk endpoint's `rows` into `${id}:${field}` → first error CODE.
 * Rows without a numeric id, or whose errors aren't code arrays, are skipped
 * defensively (the server always emits codes, but the UI must never crash on drift).
 */
export function parseBulkItemErrors(rows: unknown): Record<string, string> {
	const map: Record<string, string> = {};
	if (!Array.isArray(rows)) return map;
	for (const row of rows as BulkErrorRow[]) {
		const rawId = row?.id;
		// A null/empty id is malformed — never coerce it to 0 (Number(null) === 0).
		if (rawId == null || rawId === '') continue;
		const id = typeof rawId === 'number' ? rawId : Number(rawId);
		if (!Number.isFinite(id)) continue;
		const errors = row?.errors;
		if (!errors || typeof errors !== 'object') continue;
		for (const [field, value] of Object.entries(errors)) {
			const code = Array.isArray(value) ? value[0] : value;
			if (typeof code === 'string') {
				map[cellErrorKey(id, field)] = code;
			}
		}
	}
	return map;
}

/**
 * Flatten the bulk-CREATE endpoint's `rows` into `index` → (`field` → CODE). New lines carry no
 * id yet, so bulk-create keys its per-row errors by `index` only (Excel-paste, spec §5 п.12).
 * The Excel-paste dialog reads this to highlight the offending preview rows/cells without closing.
 */
export function parseBulkCreateItemErrors(rows: unknown): Record<number, Record<string, string>> {
	const map: Record<number, Record<string, string>> = {};
	if (!Array.isArray(rows)) return map;
	for (const row of rows as BulkErrorRow[]) {
		const index = row?.index;
		if (typeof index !== 'number' || !Number.isFinite(index)) continue;
		const errors = row?.errors;
		if (!errors || typeof errors !== 'object') continue;
		const fieldMap: Record<string, string> = {};
		for (const [field, value] of Object.entries(errors)) {
			const code = Array.isArray(value) ? value[0] : value;
			if (typeof code === 'string') fieldMap[field] = code;
		}
		if (Object.keys(fieldMap).length > 0) map[index] = fieldMap;
	}
	return map;
}

/** Extract `rows` from an Axios-style bulk error, or null if it isn't the bulk shape. */
export function extractBulkErrorRows(err: unknown): unknown | null {
	if (!err || typeof err !== 'object') return null;
	const data = (err as { response?: { data?: { detail?: unknown; rows?: unknown } } }).response?.data;
	if (data?.detail !== 'QUOTE_ITEMS_BULK_INVALID') return null;
	return data.rows ?? [];
}

/**
 * Optimistic-lock conflict code (волна 3): a save carried a STALE `version` — a colleague saved
 * that line since it was read. Unlike a validation error, this isn't a bad input the seller can
 * fix inline: their data is behind the server, so the UI opens a refresh dialog rather than a
 * cell highlight (crm/services/quotes + QuoteItemViewSet emit this same code).
 */
export const QUOTE_ITEM_STALE = 'QUOTE_ITEM_STALE';

/**
 * The row ids in a bulk `rows` payload whose error is a version conflict (QUOTE_ITEM_STALE).
 * A non-empty result means the batch was a CONCURRENCY conflict, not a validation failure — the
 * grid opens the conflict dialog for exactly these rows instead of highlighting cells.
 */
export function extractStaleConflictIds(rows: unknown): number[] {
	const ids: number[] = [];
	if (!Array.isArray(rows)) return ids;
	for (const row of rows as BulkErrorRow[]) {
		const versionError = row?.errors?.version;
		const code = Array.isArray(versionError) ? versionError[0] : versionError;
		if (code !== QUOTE_ITEM_STALE) continue;
		const rawId = row?.id;
		if (rawId == null || rawId === '') continue;
		const id = typeof rawId === 'number' ? rawId : Number(rawId);
		if (Number.isFinite(id)) ids.push(id);
	}
	return ids;
}

/** True when an Axios-style error is a single-PATCH 409 optimistic-lock conflict (QUOTE_ITEM_STALE). */
export function isStaleConflictError(err: unknown): boolean {
	if (!err || typeof err !== 'object') return false;
	const response = (err as { response?: { status?: number; data?: { detail?: unknown } } }).response;
	return response?.status === 409 && response?.data?.detail === QUOTE_ITEM_STALE;
}

/**
 * Fields that live ONLY in the collapsed per-line detail sub-row — an error on one of
 * them is invisible while the row is collapsed (WP-J row-marker, fast-follow ревью #317).
 */
export const DETAIL_ONLY_ERROR_FIELDS = ['customs_duty', 'discount_percent', 'lead_time_days', 'hs_code'] as const;

/**
 * Fields that live in the two cost columns, which the <1200px viewport gate drops out of the
 * main table (see `showCostColumns`). An error on one of these is only visible when the row
 * detail is expanded, so it also warrants the row-level marker on a narrow screen.
 */
export const COST_COLUMN_ERROR_FIELDS = ['frozen_base_price', 'frozen_currency'] as const;

/**
 * The offending fields of one row whose cell is currently NOT visible (collapsed detail, or a
 * cost column hidden on a narrow screen). Drives the row-level error marker + auto-expand: the
 * seller sees a red dot on the row and clicks it (or it auto-opens) to reach the hidden cell.
 */
export function hiddenErrorFields(
	cellErrors: Record<string, string>,
	id: number,
	showCostColumns: boolean,
): string[] {
	const prefix = `${id}:`;
	const detailFields = new Set<string>(DETAIL_ONLY_ERROR_FIELDS);
	const costFields = new Set<string>(COST_COLUMN_ERROR_FIELDS);
	const hidden: string[] = [];
	for (const key of Object.keys(cellErrors)) {
		if (!key.startsWith(prefix)) continue;
		const field = key.slice(prefix.length);
		if (detailFields.has(field) || (!showCostColumns && costFields.has(field))) {
			hidden.push(field);
		}
	}
	return hidden;
}
