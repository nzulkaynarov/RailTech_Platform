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

/**
 * i18n key for a deal-stage CODE. Render `t(DEAL_STAGE_LABEL_KEY[code])` instead of the
 * DB `stage_name` (Russian-only) so the label follows the UI language. Logic still
 * compares by code. Mirrors the `dealStages.*` keys in ru.json / en.json.
 */
export const DEAL_STAGE_LABEL_KEY: Record<string, string> = {
  DRAFT: 'dealStages.draft',
  KYC_PENDING: 'dealStages.kycPending',
  RFQ_OPEN: 'dealStages.rfqOpen',
  SOURCING: 'dealStages.sourcing',
  CALCULATING: 'dealStages.calculating',
  QUOTE_SENT: 'dealStages.quoteSent',
  CONTRACT_SIGNED: 'dealStages.contractSigned',
  CLOSED_WON: 'dealStages.closedWon',
  CLOSED_LOST: 'dealStages.closedLost',
};

/** i18n key for a SystemRole CODE (`roles.ADMIN` / `roles.USER`). */
export const systemRoleLabelKey = (code: string | undefined | null): string =>
  code ? `roles.${code}` : 'roles.USER';

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
