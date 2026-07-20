import type { QuoteItem, QuoteItemDisplayType } from '@/api/crmApi';

/**
 * The КП-line fields the bulk-create endpoint accepts as writable (mirror of
 * `crm.services.quotes._BULK_CREATE_WRITABLE_FIELDS`). A duplicate copies exactly
 * these from the source line — never the derived/read-only ones (landed_cost,
 * final_price_excl_vat, product binding, id). `imported_raw_name` gets a «(копия)»
 * suffix so the new line is visibly a copy; the target `quote` is bound server-side.
 */
// A type ALIAS, deliberately not an `interface`: only an alias carries an implicit index signature,
// so it is structurally assignable to the bulk-create endpoint's `Record<string, unknown>` row
// contract. That removes the `as unknown as Record<string, unknown>` cast at the call site (DT6)
// while keeping every field name/type checked.
export type DuplicateItemPayload = {
	imported_raw_name: string;
	quantity: number;
	frozen_base_price: string;
	frozen_currency: string;
	logistics_cost: string;
	customs_duty: string;
	discount_percent: string;
	lead_time_days: number;
	// S1: preserve the row TYPE + optionality so a duplicated section stays a section and an optional
	// line stays optional. A SECTION/NOTE copy still carries the (zero) pricing fields — the backend
	// SECTION_NOTE_NO_PRICING guard only rejects NON-zero pricing, so zeros pass through cleanly.
	display_type: QuoteItemDisplayType;
	is_optional: boolean;
	hs_code?: string;
	mpn?: string;
	gost_drawing?: string;
	unit?: string;
	unit_code?: string;
	note?: string;
};

/** Build the bulk-create payload row for a duplicate of `item`. `copySuffix` is i18n-provided. */
export function buildDuplicatePayload(item: QuoteItem, copySuffix: string): DuplicateItemPayload {
	const payload: DuplicateItemPayload = {
		imported_raw_name: `${item.imported_raw_name || item.product_name || ''}${copySuffix}`,
		quantity: item.quantity,
		frozen_base_price: item.frozen_base_price,
		frozen_currency: item.frozen_currency || 'UZS',
		logistics_cost: item.logistics_cost,
		customs_duty: item.customs_duty,
		discount_percent: item.discount_percent,
		lead_time_days: item.lead_time_days ?? 0,
		display_type: item.display_type ?? 'ITEM',
		is_optional: !!item.is_optional,
	};
	// Optional text fields — only forward when present, so the payload stays lean.
	if (item.hs_code) payload.hs_code = item.hs_code;
	if (item.mpn) payload.mpn = item.mpn;
	if (item.gost_drawing) payload.gost_drawing = item.gost_drawing;
	if (item.unit) payload.unit = item.unit;
	if (item.unit_code) payload.unit_code = item.unit_code;
	if (item.note) payload.note = item.note;
	return payload;
}
