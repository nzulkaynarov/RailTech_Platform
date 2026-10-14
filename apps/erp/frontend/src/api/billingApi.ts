import { apiClient } from './client';
import { PaginatedResponse } from './types';
import { downloadFile } from '@/lib/download';

// ─── Invoices ─────────────────────────────────────────────────

export type InvoiceStatus = 'DRAFT' | 'ISSUED' | 'PARTIAL' | 'PAID' | 'OVERDUE' | 'CANCELLED';

export interface InvoiceItem {
  id: number;
  description: string;
  quantity: number;
  unit_price_excl_vat: string;
  line_total_excl_vat: string;
  source_quote_item: number | null;
}

export interface Payment {
  id: number;
  invoice: number;
  amount: string;
  method: 'BANK_TRANSFER' | 'CARD' | 'CASH' | 'OTHER';
  paid_at: string;
  reference: string;
  receipt_number: string;
  proof_file: string | null;
  proof_url: string | null;
  recorded_by: number | null;
  created_at: string;
}

export interface Invoice {
  id: number;
  deal: number;
  contract: number | null;
  number: string;
  status: InvoiceStatus;
  issued_at: string | null;
  due_date: string | null;
  subtotal_excl_vat: string;
  vat_amount: string;
  total_incl_vat: string;
  amount_paid: string;
  balance_due: string;
  currency: number | null;
  pdf_file: string | null;
  pdf_url: string | null;
  notes: string;
  items: InvoiceItem[];
  payments: Payment[];
  /** Может ли зритель управлять счётом (выпуск, акт, аннулирование) — считает сервер. */
  viewer_can_manage: boolean;
  /** O3: у продавца заполнены банковские реквизиты — иначе счёт нечем оплатить. */
  seller_bank_details_ready?: boolean;
  created_at: string;
  updated_at: string;
}

export interface InvoiceFilterParams {
  status?: string;
  deal?: number;
  contract?: number;
  search?: string;
  ordering?: string;
  page?: number;
  [key: string]: string | number | boolean | undefined;
}

export const invoicesApi = {
  list: async (params?: InvoiceFilterParams) => {
    const response = await apiClient.get<PaginatedResponse<Invoice>>('crm/invoices/', { params });
    return response.data.results;
  },
  get: async (id: number) => {
    const response = await apiClient.get<Invoice>(`crm/invoices/${id}/`);
    return response.data;
  },
  downloadPdf: (id: number) => downloadFile(`crm/invoices/${id}/download-pdf/`, `Invoice_${id}.pdf`),
  // WP-G2 — «Создать инвойс с нуля». POST a deal (+ optional `source_quote` to import that КП's
  // lines) → a DRAFT Invoice with contract=null. Mirrors the Odoo «create invoice, optionally
  // from a sales order» pattern. Endpoint: the backend `create-manual` action on InvoiceViewSet.
  createDraft: async (payload: { deal: number; source_quote?: number }) => {
    const response = await apiClient.post<Invoice>('crm/invoices/create-manual/', payload);
    return response.data;
  },
  generateFromContract: async (contractId: number, dueDays = 14) => {
    const response = await apiClient.post<Invoice>('crm/invoices/generate-from-contract/', {
      contract_id: contractId,
      due_days: dueDays,
    });
    return response.data;
  },
  recordPayment: async (
    invoiceId: number,
    payload: {
      amount: string;
      paid_at: string;
      method?: string;
      reference?: string;
      proof_file?: File;
    },
  ) => {
    if (payload.proof_file) {
      const formData = new FormData();
      formData.append('amount', payload.amount);
      formData.append('paid_at', payload.paid_at);
      formData.append('method', payload.method ?? 'BANK_TRANSFER');
      formData.append('reference', payload.reference ?? '');
      formData.append('proof_file', payload.proof_file);
      const response = await apiClient.post<Payment>(
        `crm/invoices/${invoiceId}/record-payment/`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      );
      return response.data;
    }
    const response = await apiClient.post<Payment>(`crm/invoices/${invoiceId}/record-payment/`, {
      amount: payload.amount,
      paid_at: payload.paid_at,
      method: payload.method ?? 'BANK_TRANSFER',
      reference: payload.reference ?? '',
    });
    return response.data;
  },
  generateAct: async (invoiceId: number) => {
    const response = await apiClient.post<Act>(`crm/invoices/${invoiceId}/generate-act/`);
    return response.data;
  },
  // DRAFT → ISSUED: renders the PDF and notifies the buyer.
  issue: async (id: number) => {
    const response = await apiClient.post<Invoice>(`crm/invoices/${id}/issue/`);
    return response.data;
  },
  // Issued-but-unpaid → CANCELLED (backend refuses PAID/PARTIAL with INVOICE_CANNOT_CANCEL_PAID).
  cancel: async (id: number) => {
    const response = await apiClient.post<Invoice>(`crm/invoices/${id}/cancel/`);
    return response.data;
  },
  // Edits a DRAFT invoice's due date / notes (amounts come from the contract).
  updateDraft: async (id: number, payload: { due_date?: string; notes?: string }) => {
    const response = await apiClient.patch<Invoice>(`crm/invoices/${id}/`, payload);
    return response.data;
  },
};

// ─── Payments ─────────────────────────────────────────────────

export const paymentsApi = {
  list: async (params?: { invoice?: number; method?: string; page?: number }) => {
    const response = await apiClient.get<PaginatedResponse<Payment>>('crm/payments/', { params });
    return response.data.results;
  },
};

// ─── Acts ─────────────────────────────────────────────────────

export type ActStatus = 'DRAFT' | 'ISSUED' | 'SIGNED' | 'CANCELLED';

export interface Act {
  id: number;
  deal: number;
  contract: number | null;
  invoice: number | null;
  number: string;
  status: ActStatus;
  issued_at: string | null;
  signed_at: string | null;
  total_amount: string;
  pdf_file: string | null;
  pdf_url: string | null;
  signed_file: string | null;
  signed_file_url: string | null;
  /**
   * Действия ВЫПУСТИВШЕЙ стороны (A4). Считает сервер: `remind` дополнительно гаснет на сутки
   * после напоминания, `cancel` — после того как акт согласован обеими сторонами.
   */
  viewer_can_remind: boolean;
  viewer_can_cancel: boolean;
  /** Возвращённый заказчиком акт выпускает заново ТОЛЬКО исполнитель (сторону считает сервер). */
  viewer_can_reissue: boolean;
  issuer_signer: number | null;
  issuer_signer_name: string | null;
  issuer_signed_at: string | null;
  acceptor_signer: number | null;
  acceptor_signer_name: string | null;
  acceptor_signed_at: string | null;
  rejection_reason: string;
  /** Причина отзыва выпустившей стороной — отдельно от причины возврата заказчиком. */
  cancellation_reason: string;
  reminder_sent_at: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export const actsApi = {
  list: async (params?: { status?: string; deal?: number; page?: number }) => {
    const response = await apiClient.get<PaginatedResponse<Act>>('crm/acts/', { params });
    return response.data.results;
  },
  get: async (id: number) => {
    const response = await apiClient.get<Act>(`crm/acts/${id}/`);
    return response.data;
  },
  downloadPdf: (id: number) => downloadFile(`crm/acts/${id}/download-pdf/`, `Act_${id}.pdf`),
  // Повтор приглашения заказчику (не новый вид письма). Сервер откажет
  // ACT_REMINDER_TOO_SOON, если с прошлого напоминания не прошли сутки.
  remind: async (id: number) => {
    const response = await apiClient.post<Act>(`crm/acts/${id}/remind/`);
    return response.data;
  },
  // Отзыв акта выпустившей стороной: причина обязательна и уходит заказчику.
  cancel: async (id: number, reason: string) => {
    const response = await apiClient.post<Act>(`crm/acts/${id}/cancel/`, { reason });
    return response.data;
  },
  // Повторный выпуск возвращённого акта: тот же документ и тот же номер, второй не создаётся.
  reissue: async (id: number) => {
    const response = await apiClient.post<Act>(`crm/acts/${id}/reissue/`);
    return response.data;
  },
};
