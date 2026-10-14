/**
 * Типы CRM-домена, относящиеся к ИИ: подбор по каталогу, подсказка цены и сверка загруженного
 * документа. Покупательские ИИ-проверки (предполётная проверка заявки, «КП vs заявка») удалены
 * в M1-ERP-02 волна 3.
 *
 * Вынесено из crmApi.ts при распиле (самый горячий файл: 1179 строк, 56 правок).
 */

// ─── AI catalog match (sourcing/match-catalog) ───────────────────────────
// A single catalog product proposed for an unmatched КП line.
export interface CatalogCandidate {
	product_id: number;
	name: string;
	sku: string;
	confidence: number; // 0..1
	reason: string;
}

// Candidates for one POSTed line. `line_index` is the index into the `lines`
// array sent in the request (NOT the QuoteItem id) — caller maps it back.
export interface CatalogMatch {
	line_index: number;
	candidates: CatalogCandidate[];
}

export interface MatchCatalogLine {
	name: string;
	mpn?: string;
	gost_drawing?: string;
}

export interface MatchCatalogPayload {
	lines: MatchCatalogLine[];
	domain_code?: string;
	top_k?: number;
}

// ─── Pricing-assist (Move 3): suggested line cost from the seller's SupplierOffer ─────────
export interface PricingSuggestion {
	item_id: number;
	product_id: number;
	base_price: string;
	currency: string | null;
	lead_time_days: number;
	supplier_sku?: string;
	delivery_basis?: string | null;
}

// AI #6 — signed contract / counter-invoice extraction + code-side reconciliation.
// The model TRANSCRIBES these fields (untrusted OCR); the money verdict in `comparison`
// is recomputed on the backend in Decimal. line_index/totals are strings as read.
export interface DocExtractLineTotal {
	description: string;
	line_total: string;
}

export interface DocExtractedFields {
	total: string;
	currency_code: string;
	valid_until: string;
	bank_details: string;
	line_totals: DocExtractLineTotal[];
}

// Stable machine codes for each reconciliation flag (compared by code, never name).
export type DocMismatchCode =
	| 'TOTAL_MISMATCH'
	| 'CURRENCY_UNKNOWN'
	| 'FOREIGN_CURRENCY'
	| 'DOCUMENT_EXPIRED'
	| 'TOTAL_NOT_FOUND'
	| 'CURRENCY_NOT_FOUND';

export interface DocMismatch {
	code: DocMismatchCode;
	document_total?: string;
	expected_total?: string;
	difference?: string;
	document_currency?: string;
	expected_currency?: string;
	valid_until?: string;
}

export interface DocComparison {
	ok: boolean;
	mismatches: DocMismatch[];
	parsed: {
		document_total: string | null;
		document_currency: string | null;
		valid_until: string | null;
		bank_details: string | null;
		line_count: number;
	};
}

export interface DocCheckResult {
	reference: { kind: 'quote' | 'contract'; id: number };
	extracted: DocExtractedFields;
	comparison: DocComparison;
}

export interface DocCheckPayload {
	file: File;
	quoteId?: number;
	contractId?: number;
}

// Incoterms 2020 cost-responsibility flags — drive which cost rows the КП builder
// shows / requires for the selected delivery basis (code reads flags, no hardcode).
