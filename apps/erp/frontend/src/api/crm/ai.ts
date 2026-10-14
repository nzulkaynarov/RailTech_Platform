/**
 * ИИ-эндпоинты CRM и сверка документов. Все длительные вызовы идут через ARCH-01:
 * 202 + task_id и поллинг ai-status (обёртка runAiJob).
 *
 * Вынесено из crmApi.ts при распиле (1179 строк, 56 правок — самый горячий файл проекта).
 * Composed в `./index.ts`; публичный объект `crmApi` и путь `@/api/crmApi` не изменились.
 */

import { runAiJob } from '@/lib/aiJob';
import { apiClient } from '../client';
import type { NumberingPreviewInput, NumberingPreviewItem, NumberingScheme, NumberingSchemeUpdate, QuoteItem } from './types';
import type { CatalogMatch, DocCheckPayload, DocCheckResult, MatchCatalogPayload, PricingSuggestion } from './types.ai';

export const aiApi = {
	matchCandidates: async (quoteItemId: number) => {
		const response = await apiClient.get<{
			raw: string;
			candidates: Array<{ product_id: number; sku: string; name: string; gost: string; score: number }>;
		}>(`crm/quote-items/${quoteItemId}/match-candidates/`);
		return response.data;
	},
	reassignProduct: async (quoteItemId: number, productId: number | null) => {
		const response = await apiClient.post<QuoteItem>(
			`crm/quote-items/${quoteItemId}/reassign-product/`,
			{ product_id: productId },
		);
		return response.data;
	},

	// ─── AI catalog match ────────────────────────────────────
	// POST a batch of unmatched lines → candidate catalog products per line.
	// Only lines with ≥1 candidate are returned; may 503 {error:'AI_DISABLED'}.
	// ARCH-01: 202 + task_id, resolved via the ai-status poll (same return shape).
	matchCatalog: async (payload: MatchCatalogPayload) => {
		return runAiJob<{ matches: CatalogMatch[] }>(async () => {
			const response = await apiClient.post<{ task_id: string }>(
				'sourcing/match-catalog/',
				payload,
			);
			return response.data;
		});
	},

	// ─── Pricing-assist (Move 3) ─────────────────────────────
	// GET suggested line costs from the seller's own SupplierOffers for the КП's matched lines.
	// Cost-confidential (only the owning seller); empty {suggestions:[]} when no offers match.
	pricingAssist: async (quoteId: number) => {
		const response = await apiClient.get<{ suggestions: PricingSuggestion[] }>(
			`crm/quotes/${quoteId}/pricing-assist/`,
		);
		return response.data;
	},

	// ─── AI draft-КП generation (Move 3) ─────────────────────
	// Build a pre-filled draft КП from the buyer request (copied lines + pricing-assist on matches).
	// ARCH-01: 202 + task_id, resolved via the ai-status poll. Service gate errors arrive in
	// the result as {error: CODE} and are re-thrown as Error(CODE) for the apiErrors.* map.
	generateDraftQuote: async (dealId: number) => {
		return runAiJob<{ prefilled: number; quote_id: number }>(async () => {
			const response = await apiClient.post<{ task_id: string }>(
				`crm/deals/${dealId}/generate-draft-quote/`,
				{},
			);
			return response.data;
		});
	},

	/**
	 * W2 «одна кнопка» (one-click-quotation): claim + стадия + предзаполненный КП.
	 * Бэкенд отвечает 200 {mode:'quote', quote_id} (без AI — КП уже готов) либо
	 * 202 {mode:'ai', task_id} — тогда поллим существующий ai-status до готовности.
	 * В обоих случаях резолвимся, когда КП существует и можно открывать билдер.
	 */
	takeAndPrepareQuote: async (dealId: number): Promise<{ quote_id?: number }> => {
		const response = await apiClient.post<{ mode: string; task_id?: string; quote_id?: number }>(
			`crm/deals/${dealId}/take-and-prepare/`,
			{},
		);
		if (response.data.mode === 'quote') return { quote_id: response.data.quote_id };
		const taskId = response.data.task_id as string;
		return runAiJob<{ prefilled: number; quote_id: number }>(async () => ({ task_id: taskId }));
	},

	// ─── AI #6 contract/invoice extraction + reconciliation ──
	// POST a signed contract/counter-invoice PDF + a quote OR contract id → extracted
	// fields and a CODE-computed (Decimal) comparison vs the КП/Contract record. The
	// money verdict comes from the backend; LLM numbers are never trusted. May 503.
	// ARCH-01: the multipart POST is unchanged, but the view now returns 202 + task_id;
	// the vision extraction runs on Celery and the result comes from the ai-status poll.
	checkDocument: async ({ file, quoteId, contractId }: DocCheckPayload) => {
		const formData = new FormData();
		formData.append('file', file);
		if (quoteId != null) formData.append('quote_id', String(quoteId));
		if (contractId != null) formData.append('contract_id', String(contractId));
		return runAiJob<DocCheckResult>(async () => {
			const response = await apiClient.post<{ task_id: string }>(
				'sourcing/extract-document/',
				formData,
				{ headers: { 'Content-Type': 'multipart/form-data' } },
			);
			return response.data;
		});
	},

	// Q2 — импорт позиций КП из файла продавцом: multipart POST → 202+task_id, извлечение на
	// Celery (Excel/PDF/фото), результат {added, recognized, truncated} из ai-status поллинга.
	importQuoteLinesFromFile: async (quoteId: number, file: File) => {
		const formData = new FormData();
		formData.append('file', file);
		formData.append('quote_id', String(quoteId));
		return runAiJob<{ added: number; recognized: number; truncated: boolean; quote_id: number }>(async () => {
			const response = await apiClient.post<{ task_id: string }>(
				'sourcing/import-quote-lines/',
				formData,
				{ headers: { 'Content-Type': 'multipart/form-data' } },
			);
			return response.data;
		});
	},

	// ─── N2: document-numbering-scheme editor (Settings → «Нумерация») ────────
	// The seller company's effective numbering scheme + brand prefix. A custom mask
	// is only EFFECTIVE (`is_effective`) while the company carries a non-empty prefix
	// (global-unique invariant); prefix-less it mints under the platform default.
	getNumberingScheme: async () => {
		const response = await apiClient.get<NumberingScheme>('crm/numbering-scheme/');
		return response.data;
	},
	updateNumberingScheme: async (data: NumberingSchemeUpdate) => {
		const response = await apiClient.patch<NumberingScheme>('crm/numbering-scheme/', data);
		return response.data;
	},
	// Dry-run: render КП/CT/INV examples for a DRAFT scheme WITHOUT touching any counter.
	// Same token parser as real minting — the single source of truth for the live preview.
	previewNumberingScheme: async (data: NumberingPreviewInput) => {
		const response = await apiClient.post<{ results: NumberingPreviewItem[] }>(
			'crm/numbering-scheme/preview/',
			data,
		);
		return response.data.results;
	},
};
