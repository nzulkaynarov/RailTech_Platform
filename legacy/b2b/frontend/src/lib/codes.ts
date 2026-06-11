/**
 * Single source of truth for backend lookup CODES on the frontend.
 *
 * Mirrors the backend `accounts/constants.py` + `crm/constants.py` (the `code`
 * values of seeded lookup rows). Compare `stage_code` / `status_code` against
 * these instead of bare string literals so a typo is caught by TS, and the set
 * of valid codes lives in one place. Display names still come from the API
 * (`stage_name` / `status_name`) — these are for LOGIC only (IRON RULE: compare
 * by code, never by translated name).
 */

export const DealStage = {
  DRAFT: 'DRAFT',
  KYC_PENDING: 'KYC_PENDING',
  RFQ_OPEN: 'RFQ_OPEN',
  SOURCING: 'SOURCING',
  CALCULATING: 'CALCULATING',
  QUOTE_SENT: 'QUOTE_SENT',
  CONTRACT_SIGNED: 'CONTRACT_SIGNED',
  CLOSED_WON: 'CLOSED_WON',
  CLOSED_LOST: 'CLOSED_LOST',
} as const;
export type DealStageCode = (typeof DealStage)[keyof typeof DealStage];

export const QuoteStatus = {
  DRAFT: 'DRAFT',
  PENDING_TRADE_REVIEW: 'PENDING_TRADE_REVIEW',
  PENDING_APPROVAL: 'PENDING_APPROVAL',
  READY_TO_SEND: 'READY_TO_SEND',
  SENT: 'SENT',
  APPROVED: 'APPROVED',
  REJECTED: 'REJECTED',
} as const;
export type QuoteStatusCode = (typeof QuoteStatus)[keyof typeof QuoteStatus];

export const ContractStatus = {
  DRAFT: 'DRAFT',
  PENDING_CLIENT: 'PENDING_CLIENT',
  PENDING_MANAGER: 'PENDING_MANAGER',
  SIGNED: 'SIGNED',
  CANCELLED: 'CANCELLED',
} as const;

export const FulfillmentStatus = {
  PENDING: 'PENDING',
  SHIPPED: 'SHIPPED',
  IN_TRANSIT: 'IN_TRANSIT',
  DELIVERED: 'DELIVERED',
  ACCEPTED: 'ACCEPTED',
  DISPUTED: 'DISPUTED',
} as const;

export const SupplierBidStatus = {
  DRAFT: 'DRAFT',
  SUBMITTED: 'SUBMITTED',
  ACCEPTED: 'ACCEPTED',
  REJECTED: 'REJECTED',
  WITHDRAWN: 'WITHDRAWN',
} as const;

export const CompanyType = {
  CLIENT: 'CLIENT',
  SUPPLIER: 'SUPPLIER',
  MANUFACTURER: 'MANUFACTURER',
} as const;

export const VerificationStatus = {
  L1_UNVERIFIED: 'L1_UNVERIFIED',
  PROFILE_SUBMITTED: 'PROFILE_SUBMITTED',
  L2_VERIFIED: 'L2_VERIFIED',
  L3_CONTRACTED: 'L3_CONTRACTED',
} as const;
