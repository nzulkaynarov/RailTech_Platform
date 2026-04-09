import { create } from 'zustand';

/* ═══════════════════════════════════════════════════════════════════════
   FULL B2B PROCUREMENT FLOW — Data Model

   Flow: Client → Seller → Manufacturer → Seller → Client → Deal

   1. Client (UTY) imports Excel → SourcingRequest created
   2. Seller (RT) receives matched items → reviews availability
   3. Seller sends RFQs to manufacturers for missing items
   4. Manufacturers respond with prices + lead times
   5. Seller calculates landed cost → sends КП to client
   6. Client reviews КП → Accept / Reject
   7. If accepted → Deal opens with FSM stages
   ═══════════════════════════════════════════════════════════════════════ */

/* ─── Companies in the demo ──────────────────────────────────────────── */

export interface DemoCompany {
  id: string;
  name: string;
  type: 'buyer' | 'seller' | 'manufacturer';
  inn: string;
}

// Loaded from API via accountsApi
export const demoCompanies: DemoCompany[] = [];

/* ─── Request Item (line from Excel import) ──────────────────────────── */

export type MatchStatus = 'matched' | 'partial' | 'not_found';

export interface RequestItem {
  id: string;
  /** Original line from Excel */
  name: string;
  article: string;
  gost: string;
  uom: string;
  quantity: number;
  /** Matching result */
  matchStatus: MatchStatus;
  matchedProductId?: string;
  /** Which manufacturer makes this */
  manufacturerId?: string;
  manufacturerName?: string;
  /** Seller has access from this manufacturer? */
  sellerHasAccess: boolean;
  /** Is it in seller's stock? */
  inSellerStock: boolean;
  /** Manufacturer's base price for this seller (partner price) */
  partnerPriceFCA?: number;
  /** RFQ fields — manufacturer fills these */
  rfqStatus: 'not_sent' | 'sent' | 'responded' | 'declined';
  rfqPrice?: number;
  rfqLeadDays?: number;
  rfqNote?: string;
  /** Seller cost calculation */
  logisticsCost?: number;
  customsDuty?: number;
  landedCost?: number;
  marginPercent?: number;
  finalPrice?: number;
  finalPriceWithVAT?: number;
}

/* ─── Sourcing Request (the whole request from client) ───────────────── */

export type RequestStatus =
  | 'draft'            // Client is editing
  | 'submitted'        // Client submitted
  | 'processing'       // Seller is working on it
  | 'rfq_sent'         // Seller sent RFQs to manufacturers
  | 'rfq_received'     // Manufacturers responded
  | 'calculating'      // Seller is calculating costs
  | 'kp_sent'          // КП sent to client
  | 'kp_review'        // Client is reviewing
  | 'kp_accepted'      // Client accepted → Deal
  | 'kp_rejected'      // Client rejected
  | 'deal_opened';     // Deal created

/** i18n keys for request status labels — use with t(`requestStatuses.${status}`) */
export const requestStatusLabels: Record<RequestStatus, string> = {
  draft: 'requestStatuses.draft',
  submitted: 'requestStatuses.submitted',
  processing: 'requestStatuses.processing',
  rfq_sent: 'requestStatuses.rfq_sent',
  rfq_received: 'requestStatuses.rfq_received',
  calculating: 'requestStatuses.calculating',
  kp_sent: 'requestStatuses.kp_sent',
  kp_review: 'requestStatuses.kp_review',
  kp_accepted: 'requestStatuses.kp_accepted',
  kp_rejected: 'requestStatuses.kp_rejected',
  deal_opened: 'requestStatuses.deal_opened',
};

export const requestStatusColors: Record<RequestStatus, string> = {
  draft: 'bg-muted text-muted-foreground border-border',
  submitted: 'bg-info/10 text-info border-info/20',
  processing: 'bg-info/10 text-info border-info/20',
  rfq_sent: 'bg-accent text-accent-foreground border-border',
  rfq_received: 'bg-warning/10 text-warning border-warning/20',
  calculating: 'bg-warning/10 text-warning border-warning/20',
  kp_sent: 'bg-info/10 text-info border-info/20',
  kp_review: 'bg-warning/10 text-warning border-warning/20',
  kp_accepted: 'bg-success/10 text-success border-success/20',
  kp_rejected: 'bg-destructive/10 text-destructive border-destructive/20',
  deal_opened: 'bg-success/10 text-success border-success/20',
};

export interface SourcingRequest {
  id: string;
  number: string;
  clientId: string;
  clientName: string;
  sellerId: string;
  sellerName: string;
  status: RequestStatus;
  items: RequestItem[];
  createdAt: string;
  updatedAt: string;
  /** Client rejection reason */
  rejectionReason?: string;
  rejectionComment?: string;
  /** Deal ID if accepted */
  dealId?: string;
}

/* ─── Deal (after КП accepted) ──────────────────────────────────────── */

export type DealStage =
  | 'DRAFT'
  | 'KYC_PENDING'
  | 'SOURCING'
  | 'CALCULATING'
  | 'QUOTE_SENT'
  | 'CONTRACT_SIGNED'
  | 'CLOSED_WON'
  | 'CLOSED_LOST';

/** i18n KEYS — translate in components via t(dealStageLabels[stage]) */
export const dealStageLabels: Record<DealStage, string> = {
  DRAFT: 'dealStages.draft',
  KYC_PENDING: 'dealStages.kycPending',
  SOURCING: 'dealStages.sourcing',
  CALCULATING: 'dealStages.calculating',
  QUOTE_SENT: 'dealStages.quoteSent',
  CONTRACT_SIGNED: 'dealStages.contractSigned',
  CLOSED_WON: 'dealStages.closedWon',
  CLOSED_LOST: 'dealStages.closedLost',
};

export const dealStageColors: Record<DealStage, string> = {
  DRAFT: 'bg-muted text-muted-foreground',
  KYC_PENDING: 'bg-warning/10 text-warning',
  SOURCING: 'bg-info/10 text-info',
  CALCULATING: 'bg-warning/10 text-warning',
  QUOTE_SENT: 'bg-info/10 text-info',
  CONTRACT_SIGNED: 'bg-success/10 text-success',
  CLOSED_WON: 'bg-success/10 text-success',
  CLOSED_LOST: 'bg-destructive/10 text-destructive',
};

export interface Deal {
  id: string;
  number: string;
  stage: DealStage;
  clientName: string;
  totalAmount: number;
  totalAmountWithVAT: number;
  itemCount: number;
  requestId: string;
  createdAt: string;
  manager: string;
}

/* ═══════════════════════════════════════════════════════════════════════
   DEMO DATA — Pre-populated scenario
   ═══════════════════════════════════════════════════════════════════════ */

// Creates an empty sourcing request structure for new requests
// Live data is loaded from the API via sourcingApi
function createDemoRequest(): SourcingRequest {
  return {
    id: '',
    number: '',
    clientId: '',
    clientName: '',
    sellerId: '',
    sellerName: '',
    status: 'draft',
    items: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

/* ═══════════════════════════════════════════════════════════════════════
   ZUSTAND STORE — Flow state machine
   ═══════════════════════════════════════════════════════════════════════ */

interface FlowState {
  request: SourcingRequest;
  deal: Deal | null;

  /* ── Actions ────────────────────────────────────────────────────── */

  /** Load sourcing requests from API */
  loadFromApi: () => Promise<void>;

  /** Fetch deals from API */
  fetchDeals: () => Promise<void>;

  /** Step 2: Seller starts processing */
  sellerStartProcessing: () => void;

  /** Step 3: Seller sends RFQs to manufacturers for items not in stock */
  sellerSendRFQs: () => void;

  /** Step 4: Manufacturer responds with price + lead time */
  manufacturerRespond: (itemId: string, price: number, leadDays: number, note?: string) => void;
  manufacturerRespondAll: () => void;

  /** Step 5: Seller calculates landed cost for all items */
  sellerCalculate: (marginPercent: number) => void;

  /** Step 6: Seller sends КП to client */
  sellerSendKP: () => void;

  /** Step 7a: Client accepts КП → opens Deal */
  clientAcceptKP: () => void;

  /** Step 7b: Client rejects КП */
  clientRejectKP: (reason: string, comment?: string) => void;

  /** Update item field (for manufacturer price entry) */
  updateItem: (itemId: string, updates: Partial<RequestItem>) => void;

  /** Reset flow to initial state */
  resetFlow: () => void;
}

export const useFlowStore = create<FlowState>((set, get) => ({
  request: createDemoRequest(),
  deal: null,

  loadFromApi: async () => {
    try {
      const { sourcingApi } = await import('../api/sourcingApi');
      const requests = await sourcingApi.getRequests();
      if (requests.length > 0) {
        const firstRequest = requests[0];
        set({
          request: {
            id: String(firstRequest.id),
            number: firstRequest.number,
            clientId: '',
            clientName: firstRequest.client_name,
            sellerId: '',
            sellerName: '',
            status: firstRequest.status as RequestStatus,
            items: [],
            createdAt: firstRequest.created_at,
            updatedAt: firstRequest.created_at,
          },
        });
      }
    } catch (error) {
      console.error('Failed to load sourcing requests from API:', error);
    }
  },

  fetchDeals: async () => {
    try {
      const { crmApi } = await import('../api/crmApi');
      const deals = await crmApi.getDeals();
      if (deals.length > 0) {
        const firstDeal = deals[0];
        const deal: Deal = {
          id: String(firstDeal.id),
          number: firstDeal.id?.toString() || '',
          stage: (firstDeal.stage_name as DealStage) || 'DRAFT',
          clientName: firstDeal.client_name || '',
          totalAmount: 0,
          totalAmountWithVAT: 0,
          itemCount: 0,
          requestId: '',
          createdAt: firstDeal.created_at,
          manager: '',
        };
        set({ deal });
      }
    } catch (error) {
      console.error('Failed to load deals from API:', error);
    }
  },

  sellerStartProcessing: () =>
    set((s) => ({
      request: { ...s.request, status: 'processing', updatedAt: new Date().toISOString() },
    })),

  sellerSendRFQs: () =>
    set((s) => {
      const items = s.request.items.map((item) => {
        // Send RFQ for items that are matched/partial, seller has access, but NOT in stock
        if (item.sellerHasAccess && !item.inSellerStock && item.matchStatus !== 'not_found') {
          return { ...item, rfqStatus: 'sent' as const };
        }
        return item;
      });
      return {
        request: { ...s.request, items, status: 'rfq_sent', updatedAt: new Date().toISOString() },
      };
    }),

  manufacturerRespond: (itemId, price, leadDays, note) =>
    set((s) => {
      const items = s.request.items.map((item) =>
        item.id === itemId
          ? { ...item, rfqStatus: 'responded' as const, rfqPrice: price, rfqLeadDays: leadDays, rfqNote: note }
          : item
      );
      const allRFQsDone = items
        .filter((i) => i.rfqStatus === 'sent' || i.rfqStatus === 'responded')
        .every((i) => i.rfqStatus === 'responded');
      return {
        request: {
          ...s.request,
          items,
          status: allRFQsDone ? 'rfq_received' : s.request.status,
          updatedAt: new Date().toISOString(),
        },
      };
    }),

  manufacturerRespondAll: () =>
    set((s) => {
      const items = s.request.items.map((item) => {
        if (item.rfqStatus === 'sent') {
          // Simulate manufacturer responses
          const basePrice = item.partnerPriceFCA ?? 5000;
          const price = Math.round(basePrice * (0.9 + Math.random() * 0.3));
          const leadDays = Math.floor(14 + Math.random() * 30);
          return {
            ...item,
            rfqStatus: 'responded' as const,
            rfqPrice: price,
            rfqLeadDays: leadDays,
            rfqNote: item.manufacturerName ?? '',
          };
        }
        return item;
      });
      return {
        request: { ...s.request, items, status: 'rfq_received', updatedAt: new Date().toISOString() },
      };
    }),

  sellerCalculate: (marginPercent) =>
    set((s) => {
      const items = s.request.items.map((item) => {
        if (!item.sellerHasAccess || item.matchStatus === 'not_found') return item;

        const basePrice = item.inSellerStock
          ? (item.partnerPriceFCA ?? 0)
          : (item.rfqPrice ?? item.partnerPriceFCA ?? 0);

        if (basePrice === 0) return item;

        // Landed cost calculation: FCA + logistics (8%) + customs (5%)
        const logisticsCost = Math.round(basePrice * 0.08);
        const customsDuty = Math.round(basePrice * 0.05);
        const landedCost = basePrice + logisticsCost + customsDuty;
        const finalPrice = Math.round(landedCost * (1 + marginPercent / 100));
        const finalPriceWithVAT = Math.round(finalPrice * 1.12);

        return {
          ...item,
          logisticsCost,
          customsDuty,
          landedCost,
          marginPercent,
          finalPrice,
          finalPriceWithVAT,
        };
      });
      return {
        request: { ...s.request, items, status: 'calculating', updatedAt: new Date().toISOString() },
      };
    }),

  sellerSendKP: () =>
    set((s) => ({
      request: { ...s.request, status: 'kp_sent', updatedAt: new Date().toISOString() },
    })),

  clientAcceptKP: () => {
    const req = get().request;
    const totalWithVAT = req.items.reduce((sum, i) => sum + (i.finalPriceWithVAT ?? 0) * i.quantity, 0);
    const totalNoVAT = req.items.reduce((sum, i) => sum + (i.finalPrice ?? 0) * i.quantity, 0);
    const deal: Deal = {
      id: '',
      number: '',
      stage: 'CONTRACT_SIGNED',
      clientName: req.clientName,
      totalAmount: totalNoVAT,
      totalAmountWithVAT: totalWithVAT,
      itemCount: req.items.filter((i) => i.finalPrice).length,
      requestId: req.id,
      createdAt: new Date().toISOString(),
      manager: '',
    };
    set({
      request: { ...req, status: 'deal_opened', dealId: deal.id, updatedAt: new Date().toISOString() },
      deal,
    });
  },

  clientRejectKP: (reason, comment) =>
    set((s) => ({
      request: {
        ...s.request,
        status: 'kp_rejected',
        rejectionReason: reason,
        rejectionComment: comment,
        updatedAt: new Date().toISOString(),
      },
    })),

  updateItem: (itemId, updates) =>
    set((s) => ({
      request: {
        ...s.request,
        items: s.request.items.map((i) => (i.id === itemId ? { ...i, ...updates } : i)),
      },
    })),

  resetFlow: () => set({ request: createDemoRequest(), deal: null }),
}));
