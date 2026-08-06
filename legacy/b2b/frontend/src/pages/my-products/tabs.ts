import type { ProductListParams } from '@/api/catalogApi';

/**
 * Табы единого реестра «Мои товары» (R2, аудит §5.2) — статус как таб, по образцу
 * Akeneo/Shopify Products. DRAFT дополнительно делится по происхождению: `rfq` — кандидаты
 * из заявок (есть спрос или исходная сделка), `manual` — заведённые руками черновики.
 */
export type MyProductsTabKey = 'CANDIDATES' | 'DRAFTS' | 'PUBLISHED' | 'ARCHIVED';

export const MY_PRODUCTS_TABS: MyProductsTabKey[] = ['CANDIDATES', 'DRAFTS', 'PUBLISHED', 'ARCHIVED'];

/** Серверные параметры выборки каждого таба (статусы — коды из справочника, Rule 2). */
export const TAB_LIST_PARAMS: Record<MyProductsTabKey, Pick<ProductListParams, 'status' | 'origin'>> = {
  CANDIDATES: { status: 'DRAFT', origin: 'rfq' },
  DRAFTS: { status: 'DRAFT', origin: 'manual' },
  PUBLISHED: { status: 'PUBLISHED' },
  ARCHIVED: { status: 'ARCHIVED' },
};
