import type { Deal, Quote } from '@/api/crmApi';

/**
 * Wave B2 — pure composition of the «Отправить клиенту» summary (Odoo send-composer pattern).
 *
 * Kept framework-free so it is unit-tested without React: the SendQuoteDialog renders these
 * facts, and QuoteSentPanel reuses `resolveDecision`. Every line degrades gracefully — a missing
 * recipient / economics / approval chain is a defined state, never a crash.
 */

/** «Маржа vs порог» state. `hidden` = the sender has no cost/margin visibility (economics null),
 *  so the summary shows a neutral note and the below-floor justification is prompted REACTIVELY
 *  (after the backend returns BELOW_FLOOR_JUSTIFICATION_REQUIRED) rather than up-front. */
export type MarginState = 'ok' | 'below' | 'hidden';

/** «Согласование» state. `auto` = no real chain (solo / all-auto) → «согласовано автоматически».
 *  `approved` = a real chain that is fully decided. `pending` = still awaiting an approver. */
export type ApprovalState = 'auto' | 'approved' | 'pending';

export interface SendSummary {
  /** Display name of the recipient, or null → a recipient is required (RECIPIENT_REQUIRED). */
  recipient: string | null;
  /** КП validity date (ISO), or null when no срок действия is set yet. */
  validUntil: string | null;
  marginState: MarginState;
  /** gross margin ON PRICE (governance metric), as the raw decimal string, or null when hidden. */
  marginPercent: string | null;
  /** company margin floor, as the raw decimal string, or null when hidden. */
  floorPercent: string | null;
  approvalState: ApprovalState;
  /** Names of the real approvers (APPROVER + HEAD steps), for the «кто согласовал» line. */
  approvers: string[];
}

export function composeSendSummary(deal: Deal, quote: Quote): SendSummary {
  // Recipient: the registered client, the offline contact, or the client company. The send path
  // resolves the actual email server-side (resolve_quote_recipient); we only display who it goes
  // to — contact_name covers the seller-created deal with an offline client (deal.company NULL).
  const recipient = deal.client_name || deal.contact_name || deal.company_name || null;

  const economics = quote.economics ?? null;
  let marginState: MarginState = 'hidden';
  let marginPercent: string | null = null;
  let floorPercent: string | null = null;
  if (economics) {
    marginPercent = economics.gross_margin_percent;
    floorPercent = economics.min_margin_percent;
    marginState = economics.below_floor ? 'below' : 'ok';
  }

  const steps = quote.approval_steps ?? [];
  // A real chain has at least one NON-auto step (a colleague / head who must actually decide).
  // Solo / all-auto chains (or no chain at all) are «согласовано автоматически».
  const realSteps = steps.filter((step) => !step.is_auto);
  let approvalState: ApprovalState;
  if (realSteps.length === 0) {
    approvalState = 'auto';
  } else {
    const anyPending = realSteps.some((step) => step.status === 'PENDING');
    approvalState = anyPending ? 'pending' : 'approved';
  }
  const approvers = steps
    .filter((step) => step.participation === 'APPROVER' || step.participation === 'HEAD')
    .map((step) => step.approver_name)
    .filter((name): name is string => !!name);

  return { recipient, validUntil: quote.valid_until ?? null, marginState, marginPercent, floorPercent, approvalState, approvers };
}

/** Post-send decision state derived from the КП status CODE (never the translated name). */
export type QuoteDecision = 'accepted' | 'rejected' | 'pending';

export function resolveDecision(statusCode: string): QuoteDecision {
  if (statusCode === 'APPROVED') return 'accepted';
  if (statusCode === 'REJECTED') return 'rejected';
  return 'pending';
}

/** Build the public no-login КП URL from the share token, mirroring the backend
 *  `crm/services/documents.py::public_quote_url` ({origin}/api/v1/public/quotes/{token}/).
 *  Returns null when the token is not exposed (draft / pre-send / backend not yet updated). */
export function publicQuoteUrl(token: string | null | undefined, origin: string): string | null {
  if (!token) return null;
  return `${origin}/api/v1/public/quotes/${token}/`;
}
