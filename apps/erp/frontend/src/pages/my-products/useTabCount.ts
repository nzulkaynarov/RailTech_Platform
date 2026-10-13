import { useProductsPage } from '@/hooks/useCatalog';
import type { ProductListParams } from '@/api/catalogApi';

/**
 * Серверный счётчик для бейджа таба (R2, аудит §5.2): дешёвый запрос `page_size: 1` —
 * нам нужен только `count`, тело страницы не читается. Ключ React Query включает все
 * параметры, поэтому счётчики всех табов живут в кеше независимо и сбрасываются той же
 * инвалидацией `['products']`, что и основной список (publish/archive/restore и т.д.).
 *
 * Счётчик НАМЕРЕННО не включает поиск и фильтры: бейдж отвечает «сколько всего в этом
 * состоянии», а не «сколько нашлось по запросу» — как счётчики статусов у Shopify Products.
 */
export function useTabCount(params: ProductListParams): number | undefined {
  const { data } = useProductsPage({ ...params, mine: true, page: 1, page_size: 1 });
  return data?.count;
}
