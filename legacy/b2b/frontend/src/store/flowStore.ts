import { create } from 'zustand';
import type { Deal, Quote } from '../api/crmApi';

export type DealStage =
  | 'DRAFT'
  | 'KYC_PENDING'
  | 'SOURCING'
  | 'CALCULATING'
  | 'QUOTE_SENT'
  | 'CONTRACT_SIGNED'
  | 'CLOSED_WON'
  | 'CLOSED_LOST';

export const dealStageLabels: Record<string, string> = {
  DRAFT: 'dealStages.draft',
  KYC_PENDING: 'dealStages.kycPending',
  SOURCING: 'dealStages.sourcing',
  CALCULATING: 'dealStages.calculating',
  QUOTE_SENT: 'dealStages.quoteSent',
  CONTRACT_SIGNED: 'dealStages.contractSigned',
  CLOSED_WON: 'dealStages.closedWon',
  CLOSED_LOST: 'dealStages.closedLost',
};

export const dealStageColors: Record<string, string> = {
  DRAFT: 'bg-muted text-muted-foreground',
  KYC_PENDING: 'bg-warning/10 text-warning',
  SOURCING: 'bg-info/10 text-info',
  CALCULATING: 'bg-warning/10 text-warning',
  QUOTE_SENT: 'bg-info/10 text-info',
  CONTRACT_SIGNED: 'bg-success/10 text-success',
  CLOSED_WON: 'bg-success/10 text-success',
  CLOSED_LOST: 'bg-destructive/10 text-destructive',
};

interface FlowState {
  activeDealId: number | null;
  deal: Deal | null;
  quote: Quote | null;
  loading: boolean;
  error: string | null;

  setActiveDealId: (id: number | null) => void;
  loadDeal: (id: number) => Promise<void>;
  changeDealStage: (id: number, stage: string) => Promise<void>;
  approveQuote: (quoteId: number) => Promise<void>;
  rejectQuote: (quoteId: number, reason?: string) => Promise<void>;
  sendQuoteToClient: (quoteId: number) => Promise<void>;
  resetFlow: () => void;
}

export const useFlowStore = create<FlowState>((set, get) => ({
  activeDealId: null,
  deal: null,
  quote: null,
  loading: false,
  error: null,

  setActiveDealId: (id) => set({ activeDealId: id }),

  loadDeal: async (id: number) => {
    set({ loading: true, error: null, activeDealId: id });
    try {
      const { crmApi } = await import('../api/crmApi');
      const dealData = await crmApi.getDeal(id);
      
      const quote = dealData.quotes && dealData.quotes.length > 0 
        ? dealData.quotes[dealData.quotes.length - 1] 
        : null;
      
      set({ deal: dealData, quote, loading: false });
    } catch (e: any) {
      set({ error: e.message || 'Failed to load deal', loading: false });
    }
  },

  changeDealStage: async (id: number, stage: string) => {
    set({ loading: true });
    try {
      const { crmApi } = await import('../api/crmApi');
      await crmApi.changeDealStage(id, stage);
      get().loadDeal(id);
    } catch (e: any) {
      set({ error: e.message, loading: false });
    }
  },

  approveQuote: async (quoteId: number) => {
    set({ loading: true });
    try {
      const { crmApi } = await import('../api/crmApi');
      await crmApi.approveQuote(quoteId);
      const dealId = get().deal?.id;
      if (dealId) get().loadDeal(dealId);
    } catch (e: any) {
      set({ error: e.message, loading: false });
    }
  },

  rejectQuote: async (quoteId: number, reason?: string) => {
    set({ loading: true });
    try {
      const { crmApi } = await import('../api/crmApi');
      // The API doesn't formally accept reason yet, maybe we just pass it or ignore
      await crmApi.rejectQuote(quoteId);
      const dealId = get().deal?.id;
      if (dealId) get().loadDeal(dealId);
    } catch (e: any) {
      set({ error: e.message, loading: false });
    }
  },

  sendQuoteToClient: async (quoteId: number) => {
    set({ loading: true });
    try {
      const { crmApi } = await import('../api/crmApi');
      await crmApi.sendQuoteToClient(quoteId);
      const dealId = get().deal?.id;
      if (dealId) get().loadDeal(dealId);
    } catch (e: any) {
      set({ error: e.message, loading: false });
    }
  },

  resetFlow: () => set({ activeDealId: null, deal: null, quote: null, error: null }),
}));
