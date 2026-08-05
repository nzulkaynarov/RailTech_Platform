import type { Product } from '@/api/catalogApi';

export type Draft = Partial<Product> & {
  gost_drawing?: string | null;
  description?: string;
  /** N3: владелец карточки при создании оператором (id компании; продавцу ставит сервер). */
  owner_company?: number | null;
};

export type OfferDraft = {
  base_price?: string;
  currency?: number | null;
  stock_status?: number | null;
  delivery_basis?: number | null;
  supplier_sku?: string;
  stock_quantity?: number;
  in_stock_lead_time_days?: number;
  order_lead_time_days?: number;
  /** Свободный текст срока («14-21 дн.») — печатается в публичной карточке. */
  delivery_lead_time?: string;
  min_order_qty?: number;
  /** Окно действия цены (ISO `YYYY-MM-DD`); пустая граница = открытая. */
  valid_from?: string | null;
  valid_until?: string | null;
  is_active?: boolean;
};

export function emptyDraft(): Draft {
  return { name: '', description: '', gost_drawing: '' };
}
