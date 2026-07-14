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

/** Extract `rows` from an Axios-style bulk error, or null if it isn't the bulk shape. */
export function extractBulkErrorRows(err: unknown): unknown | null {
	if (!err || typeof err !== 'object') return null;
	const data = (err as { response?: { data?: { detail?: unknown; rows?: unknown } } }).response?.data;
	if (data?.detail !== 'QUOTE_ITEMS_BULK_INVALID') return null;
	return data.rows ?? [];
}
