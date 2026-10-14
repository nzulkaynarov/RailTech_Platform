import type { DocumentKind } from '@/api/portal';

/** Виды документов контракта в порядке фильтра (подписи — `documents.kinds.*`). */
export const DOCUMENT_KINDS: DocumentKind[] = ['quote', 'contract', 'invoice', 'act', 'waybill', 'receipt', 'other'];

export function isDocumentKind(value: string | null | undefined): value is DocumentKind {
  return DOCUMENT_KINDS.includes(value as DocumentKind);
}
