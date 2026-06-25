import type { Product } from '@/api/catalogApi';

export type Draft = Partial<Product> & { gost_drawing?: string | null; description?: string };

export type OfferDraft = {
  base_price?: string;
  currency?: number | null;
  stock_status?: number | null;
  delivery_basis?: number | null;
  supplier_sku?: string;
};

export function emptyDraft(): Draft {
  return { name: '', description: '', gost_drawing: '' };
}
