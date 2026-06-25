import { apiClient } from './client';
import type { CatalogCandidate } from './crmApi';

/**
 * AI #8 — conversational заявка builder API.
 *
 * The buyer describes a need in plain text; the backend (Claude + Structured
 * Outputs, grounded in the REAL catalog) proposes structured request line items
 * the buyer reviews/edits/confirms in the grid. Nothing is auto-submitted.
 * Kept in its OWN api module (not crmApi) so the AI surface stays isolated.
 */

// One AI-proposed request line. `candidates` are REAL catalog products (ids from
// a DB trigram shortlist — never invented) the buyer may bind on accept.
export interface ComposedItem {
	name: string;
	name_canonical: string;
	quantity: number;
	unit: string;
	mpn: string;
	gost_drawing: string;
	note: string;
	candidates: CatalogCandidate[];
}

export interface ComposeRequestPayload {
	text: string;
	domain_code?: string;
}

export const aiApi = {
	// POST a free-text need → proposed structured заявка lines + catalog candidates.
	// Advisory only (buyer confirms in the grid); may 503 {error:'AI_DISABLED'}.
	composeRequest: async (payload: ComposeRequestPayload) => {
		const response = await apiClient.post<{ items: ComposedItem[] }>(
			'sourcing/compose-request/',
			payload,
		);
		return response.data;
	},
};
