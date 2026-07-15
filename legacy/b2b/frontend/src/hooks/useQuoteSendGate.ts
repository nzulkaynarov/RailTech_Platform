import { useUserStore } from '@/store/userStore';
import { isKycVerified } from '@/config/navigation';

/** Why the current seller cannot send the КП. Order mirrors the backend send_to_client gates
 * (SELLER_KYC_REQUIRED is checked before the quote.send entitlement). */
export type QuoteSendBlockReason = 'kyc' | 'subscription' | 'demo';

export interface QuoteSendGate {
  /** The viewer is acting on the seller side (the only side that sends a КП). */
  isSeller: boolean;
  /** The seller cannot send the КП yet — a KYC / entitlement / demo blocker applies. */
  blocked: boolean;
  reason: QuoteSendBlockReason | null;
  /** The stable API error code the backend would raise, for translateApiError() reuse. */
  errorCode: string | null;
}

const NOT_BLOCKED: QuoteSendGate = { isSeller: false, blocked: false, reason: null, errorCode: null };

/**
 * WP-H — proactive КП send-gate, read from /me.capabilities. Lets the builder surface a
 * KYC/subscription/demo blocker BEFORE the seller spends an hour on data entry (the audit's
 * "late surprise" at send). The evaluation order mirrors crm.services.quotes.send_to_client:
 * KYC floor first (SELLER_KYC_REQUIRED), then the quote.send entitlement (QUOTE_SEND_NOT_ENTITLED),
 * with DEMO called out distinctly. UI-gating only — send_to_client remains the authoritative gate.
 */
export function useQuoteSendGate(): QuoteSendGate {
  const role = useUserStore((s) => s.role);
  const activeStatus = useUserStore((s) => s.activeStatus);
  const capabilities = useUserStore((s) => s.capabilities);

  // Sending is a seller-side action; platform operators never act for a company.
  const isSeller = role !== 'ADMIN' && activeStatus === 'SELLER';
  if (!isSeller) return NOT_BLOCKED;

  if (!isKycVerified(capabilities.kyc_level)) {
    return { isSeller, blocked: true, reason: 'kyc', errorCode: 'SELLER_KYC_REQUIRED' };
  }
  if (capabilities.quote_send_is_demo) {
    return { isSeller, blocked: true, reason: 'demo', errorCode: 'QUOTE_SEND_NOT_ENTITLED' };
  }
  if (!capabilities.can_send_quotes) {
    return { isSeller, blocked: true, reason: 'subscription', errorCode: 'QUOTE_SEND_NOT_ENTITLED' };
  }
  return { isSeller, blocked: false, reason: null, errorCode: null };
}
