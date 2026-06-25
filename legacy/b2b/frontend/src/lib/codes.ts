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

/** WorkspaceRole CODEs (CompanyMember.role) — the per-company functional roles. */
export const WorkspaceRole = {
  OWNER: 'OWNER',
  PROCUREMENT_MANAGER: 'PROCUREMENT_MANAGER',
  BUYER_MANAGER: 'BUYER_MANAGER',
  SALES_MANAGER: 'SALES_MANAGER',
  LOGIST: 'LOGIST',
  CONTRACT_MANAGER: 'CONTRACT_MANAGER',
  FOREIGN_TRADE_SPECIALIST: 'FOREIGN_TRADE_SPECIALIST',
} as const;

/** i18n key for a WorkspaceRole CODE — render `t(workspaceRoleLabelKey(code))` instead
 * of the Russian-only DB role name. Mirrors `workspaceRoles.*` in ru.json / en.json. */
export const workspaceRoleLabelKey = (code: string | undefined | null): string =>
  code ? `workspaceRoles.${code}` : '';

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

/**
 * i18n key for a quote-status CODE. Render `t(QUOTE_STATUS_LABEL_KEY[code])` instead
 * of the DB `status_name` (Russian-only) so the label follows the UI language. Logic
 * still compares by code. Mirrors the `quoteStatuses.*` keys in ru.json / en.json.
 */
export const QUOTE_STATUS_LABEL_KEY: Record<string, string> = {
  DRAFT: 'quoteStatuses.draft',
  PENDING_TRADE_REVIEW: 'quoteStatuses.pendingTradeReview',
  PENDING_APPROVAL: 'quoteStatuses.pendingApproval',
  READY_TO_SEND: 'quoteStatuses.readyToSend',
  SENT: 'quoteStatuses.sent',
  APPROVED: 'quoteStatuses.approved',
  REJECTED: 'quoteStatuses.rejected',
};

/** Resolve a quote-status label key from a code, with a graceful fallback to the raw
 *  DB name when the code is unknown (returns `''` so callers can `|| status_name`). */
export const quoteStatusLabelKey = (code: string | undefined | null): string =>
  code && QUOTE_STATUS_LABEL_KEY[code] ? QUOTE_STATUS_LABEL_KEY[code] : '';

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

/** Product PUBLICATION-status CODEs (catalog `ProductStatus` lookup: DRAFT/PUBLISHED/
 *  ARCHIVED). Distinct from the stock-availability `productStatuses.*` keys. */
export const ProductPublicationStatus = {
  DRAFT: 'DRAFT',
  PUBLISHED: 'PUBLISHED',
  ARCHIVED: 'ARCHIVED',
} as const;

/**
 * i18n key for a product publication-status CODE. Render
 * `t(PRODUCT_STATUS_LABEL_KEY[code])` instead of the DB `status_name` (Russian-only).
 * Mirrors the `productPublicationStatuses.*` keys in ru.json / en.json.
 */
export const PRODUCT_STATUS_LABEL_KEY: Record<string, string> = {
  DRAFT: 'productPublicationStatuses.draft',
  PUBLISHED: 'productPublicationStatuses.published',
  ARCHIVED: 'productPublicationStatuses.archived',
};

/** Resolve a product publication-status label key from a code, returning `''` when
 *  unknown so callers can fall back to the raw DB name (`|| status_name`). */
export const productStatusLabelKey = (code: string | undefined | null): string =>
  code && PRODUCT_STATUS_LABEL_KEY[code] ? PRODUCT_STATUS_LABEL_KEY[code] : '';
