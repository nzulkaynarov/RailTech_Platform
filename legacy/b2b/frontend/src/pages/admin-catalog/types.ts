import type { Product } from '@/api/catalogApi';

export type Draft = Partial<Product> & { gost_drawing?: string | null; description?: string };

export type OfferDraft = {
  base_price?: string;
  currency?: number | null;
  stock_status?: number | null;
  delivery_basis?: number | null;
  supplier_sku?: string;
  stock_quantity?: number;
  in_stock_lead_time_days?: number;
  order_lead_time_days?: number;
};

export function emptyDraft(): Draft {
  return { name: '', description: '', gost_drawing: '' };
}
