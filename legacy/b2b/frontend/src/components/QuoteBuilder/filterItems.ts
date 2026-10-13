import type { QuoteItem } from '@/api/crmApi';

/**
 * U4 — «найти в КП»: pure predicate behind the builder's in-document line filter.
 *
 * Matched fields are everything a seller would type to find a line in a 200-position КП: the
 * displayed name (catalog `product_name` OR the free-typed `imported_raw_name`), the catalog
 * identity codes (артикул / ГОСТ / MPN — both the denormalised line copy and the product's), and
 * the ТН ВЭД code. SECTION and NOTE rows match on their text too, so filtering by a section title
 * keeps that heading visible.
 *
 * Deliberately a plain case-insensitive substring test (no fuzzy/regex): the seller is looking for a
 * known string, and a surprising near-match in a priced document is worse than no match. Whitespace
 * is trimmed and folded so «ГОСТ  1234» finds «ГОСТ 1234».
 */
export function normalizeFilterQuery(raw: string): string {
	return raw.trim().replace(/\s+/g, ' ').toLocaleLowerCase();
}

/** Fields a line can be found by. Empty/undefined entries are skipped. */
function searchableParts(item: QuoteItem): string[] {
	return [
		item.product_name,
		item.imported_raw_name,
		item.product_sku,
		item.product_gost,
		item.product_mpn,
		item.mpn,
		item.gost_drawing,
		item.hs_code,
	].filter((part): part is string => !!part && part.trim().length > 0);
}

/** Does this КП line match the (already raw) query? An empty query matches everything. */
export function matchesQuoteItemFilter(item: QuoteItem, rawQuery: string): boolean {
	const query = normalizeFilterQuery(rawQuery);
	if (!query) return true;
	return searchableParts(item).some((part) => normalizeFilterQuery(part).includes(query));
}

/**
 * Apply the filter to the ordered line list. Returns the SAME array reference when the query is
 * empty so the (unfiltered) common path allocates nothing and downstream memo/effect deps that key
 * on the array identity — the virtualizer count, the selection prune — do not churn.
 */
export function filterQuoteItems(items: QuoteItem[], rawQuery: string): QuoteItem[] {
	if (!normalizeFilterQuery(rawQuery)) return items;
	return items.filter((item) => matchesQuoteItemFilter(item, rawQuery));
}
