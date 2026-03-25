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

export const demoCompanies: DemoCompany[] = [
  { id: 'UTY', name: 'АО «UTY» (Узбекистон темир йуллари)', type: 'buyer', inn: '200876543' },
  { id: 'RT', name: 'OOO «RailTech»', type: 'seller', inn: '309876543' },
  { id: 'SAUT', name: 'АО «САУТ»', type: 'manufacturer', inn: '500111222' },
  { id: 'RATEP', name: 'АО «РАТЕП»', type: 'manufacturer', inn: '500333444' },
];

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

export const requestStatusLabels: Record<RequestStatus, string> = {
  draft: 'Черновик',
  submitted: 'Отправлена',
  processing: 'В обработке',
  rfq_sent: 'Запросы отправлены',
  rfq_received: 'Ответы получены',
  calculating: 'Расчёт себестоимости',
  kp_sent: 'КП отправлено',
  kp_review: 'На рассмотрении',
  kp_accepted: 'КП принято',
  kp_rejected: 'КП отклонено',
  deal_opened: 'Сделка открыта',
};

export const requestStatusColors: Record<RequestStatus, string> = {
  draft: 'bg-slate-50 text-slate-700 border-slate-200',
  submitted: 'bg-blue-50 text-blue-700 border-blue-200',
  processing: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  rfq_sent: 'bg-purple-50 text-purple-700 border-purple-200',
  rfq_received: 'bg-amber-50 text-amber-700 border-amber-200',
  calculating: 'bg-orange-50 text-orange-700 border-orange-200',
  kp_sent: 'bg-cyan-50 text-cyan-700 border-cyan-200',
  kp_review: 'bg-yellow-50 text-yellow-700 border-yellow-200',
  kp_accepted: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  kp_rejected: 'bg-red-50 text-red-700 border-red-200',
  deal_opened: 'bg-emerald-50 text-emerald-700 border-emerald-200',
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

export const dealStageLabels: Record<DealStage, string> = {
  DRAFT: 'Черновик',
  KYC_PENDING: 'KYC проверка',
  SOURCING: 'Закупка',
  CALCULATING: 'Расчёт',
  QUOTE_SENT: 'КП отправлено',
  CONTRACT_SIGNED: 'Договор подписан',
  CLOSED_WON: 'Закрыта (выиграна)',
  CLOSED_LOST: 'Закрыта (проиграна)',
};

export const dealStageColors: Record<DealStage, string> = {
  DRAFT: 'bg-slate-100 text-slate-700',
  KYC_PENDING: 'bg-amber-100 text-amber-700',
  SOURCING: 'bg-blue-100 text-blue-700',
  CALCULATING: 'bg-orange-100 text-orange-700',
  QUOTE_SENT: 'bg-cyan-100 text-cyan-700',
  CONTRACT_SIGNED: 'bg-emerald-100 text-emerald-700',
  CLOSED_WON: 'bg-green-100 text-green-700',
  CLOSED_LOST: 'bg-red-100 text-red-700',
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

function createDemoRequest(): SourcingRequest {
  return {
    id: 'SR-001',
    number: 'ЗК-2026-0047',
    clientId: 'UTY',
    clientName: 'АО «UTY»',
    sellerId: 'RT',
    sellerName: 'OOO «RailTech»',
    status: 'submitted',
    createdAt: '2026-03-18',
    updatedAt: '2026-03-18',
    items: [
      // ─── Matched, seller has access + stock ───────────────
      {
        id: 'RI-01',
        name: 'Баббит Б-83',
        article: 'MAT-001',
        gost: 'ГОСТ 1320-74',
        uom: 'тн',
        quantity: 5,
        matchStatus: 'matched',
        matchedProductId: 'P001',
        manufacturerId: 'SAUT',
        manufacturerName: 'АО «САУТ»',
        sellerHasAccess: true,
        inSellerStock: true,
        partnerPriceFCA: 14200,
        rfqStatus: 'not_sent',
      },
      {
        id: 'RI-02',
        name: 'Баббит БК-2',
        article: 'MAT-002',
        gost: 'ГОСТ 1209-90',
        uom: 'тн',
        quantity: 8,
        matchStatus: 'matched',
        matchedProductId: 'P002',
        manufacturerId: 'RATEP',
        manufacturerName: 'АО «РАТЕП»',
        sellerHasAccess: true,
        inSellerStock: true,
        partnerPriceFCA: 11800,
        rfqStatus: 'not_sent',
      },
      // ─── Matched, seller has access, NOT in stock → RFQ needed ──
      {
        id: 'RI-03',
        name: 'Провод БПВЛ 1,5 мм²',
        article: 'ELC-001',
        gost: 'ТУ16.505.911-76',
        uom: 'км',
        quantity: 50,
        matchStatus: 'matched',
        matchedProductId: 'P005',
        manufacturerId: 'SAUT',
        manufacturerName: 'АО «САУТ»',
        sellerHasAccess: true,
        inSellerStock: false,
        partnerPriceFCA: 850,
        rfqStatus: 'not_sent',
      },
      {
        id: 'RI-04',
        name: 'Круг ø120мм ст. 12ХН3А',
        article: 'MET-001',
        gost: 'ст. 12ХН3А',
        uom: 'тн',
        quantity: 10,
        matchStatus: 'matched',
        matchedProductId: 'P007',
        manufacturerId: 'SAUT',
        manufacturerName: 'АО «САУТ»',
        sellerHasAccess: true,
        inSellerStock: false,
        rfqStatus: 'not_sent',
      },
      // ─── Partial match (similar product found but spec differs) ──
      {
        id: 'RI-05',
        name: 'Провод БПВЛ 4,0 мм²',
        article: 'ELC-003',
        gost: 'ТУ16.505.911-76',
        uom: 'км',
        quantity: 30,
        matchStatus: 'partial',
        manufacturerId: 'SAUT',
        manufacturerName: 'АО «САУТ»',
        sellerHasAccess: true,
        inSellerStock: false,
        rfqStatus: 'not_sent',
      },
      // ─── Not found in catalog ─────────────────────────────
      {
        id: 'RI-06',
        name: 'Подшипник роликовый 42726',
        article: 'BRG-001',
        gost: 'ГОСТ 8328-75',
        uom: 'шт',
        quantity: 200,
        matchStatus: 'not_found',
        sellerHasAccess: false,
        inSellerStock: false,
        rfqStatus: 'not_sent',
      },
      {
        id: 'RI-07',
        name: 'Смазка ЦИАТИМ-201',
        article: 'LUB-001',
        gost: 'ГОСТ 6267-74',
        uom: 'кг',
        quantity: 500,
        matchStatus: 'not_found',
        sellerHasAccess: false,
        inSellerStock: false,
        rfqStatus: 'not_sent',
      },
      // ─── Matched, in stock ──────────────────────────────
      {
        id: 'RI-08',
        name: 'Олово марка О1 пч',
        article: 'MAT-003',
        gost: 'ГОСТ 860-75',
        uom: 'тн',
        quantity: 3,
        matchStatus: 'matched',
        matchedProductId: 'P003',
        manufacturerId: 'RATEP',
        manufacturerName: 'АО «РАТЕП»',
        sellerHasAccess: true,
        inSellerStock: true,
        partnerPriceFCA: 22500,
        rfqStatus: 'not_sent',
      },
    ],
  };
}

/* ═══════════════════════════════════════════════════════════════════════
   ZUSTAND STORE — Flow state machine
   ═══════════════════════════════════════════════════════════════════════ */

interface FlowState {
  request: SourcingRequest;
  deal: Deal | null;

  /* ── Actions ────────────────────────────────────────────────────── */

  /** Step 1: Client submits request (already done in demo data) */

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

  sellerStartProcessing: () =>
    set((s) => ({
      request: { ...s.request, status: 'processing', updatedAt: '2026-03-19' },
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
        request: { ...s.request, items, status: 'rfq_sent', updatedAt: '2026-03-19' },
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
          updatedAt: '2026-03-20',
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
            rfqNote: `Готово к отгрузке — ${item.manufacturerName ?? 'завод'}`,
          };
        }
        return item;
      });
      return {
        request: { ...s.request, items, status: 'rfq_received', updatedAt: '2026-03-20' },
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
        request: { ...s.request, items, status: 'calculating', updatedAt: '2026-03-21' },
      };
    }),

  sellerSendKP: () =>
    set((s) => ({
      request: { ...s.request, status: 'kp_sent', updatedAt: '2026-03-21' },
    })),

  clientAcceptKP: () => {
    const req = get().request;
    const totalWithVAT = req.items.reduce((sum, i) => sum + (i.finalPriceWithVAT ?? 0) * i.quantity, 0);
    const totalNoVAT = req.items.reduce((sum, i) => sum + (i.finalPrice ?? 0) * i.quantity, 0);
    const deal: Deal = {
      id: 'DEAL-001',
      number: 'СД-2026-0012',
      stage: 'CONTRACT_SIGNED',
      clientName: req.clientName,
      totalAmount: totalNoVAT,
      totalAmountWithVAT: totalWithVAT,
      itemCount: req.items.filter((i) => i.finalPrice).length,
      requestId: req.id,
      createdAt: '2026-03-21',
      manager: 'Зулкайнаров Н.А.',
    };
    set({
      request: { ...req, status: 'deal_opened', dealId: deal.id, updatedAt: '2026-03-21' },
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
        updatedAt: '2026-03-21',
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
