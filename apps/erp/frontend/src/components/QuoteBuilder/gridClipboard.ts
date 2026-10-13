import type { QuoteItem } from '@/api/crmApi';

/**
 * Serialize КП rows to TSV for the clipboard (U6 copy-out).
 *
 * The column order — name → quantity → price — is deliberately the SAME shape `parseClipboardTable`
 * detects on the way IN (Excel-paste), so a copied selection round-trips straight back through paste.
 * Tabs/newlines inside a name are flattened to spaces to keep the grid rectangular. SECTION/NOTE rows
 * carry no pricing, so only their heading/text is emitted (a name-only, single-column line).
 */
export function serializeRowsToTsv(items: QuoteItem[]): string {
	return items
		.map((item) => {
			const name = (item.product_name || item.imported_raw_name || '')
				.replace(/[\t\r\n]+/g, ' ')
				.trim();
			if ((item.display_type ?? 'ITEM') !== 'ITEM') return name;
			const quantity = item.quantity ?? '';
			const price = item.frozen_base_price ?? '';
			return `${name}\t${quantity}\t${price}`;
		})
		.join('\n');
}
