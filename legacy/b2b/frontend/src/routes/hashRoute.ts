/**
 * Хэш-маршрутизация SPA (ADR: React Router не используется).
 *
 * Тип `Page` выводится из реестра страниц, поэтому список маршрутов не приходится
 * поддерживать дважды. Отдельно перечислены только параметризованные маршруты —
 * те, что несут в хэше идентификатор.
 */

import type { PageId } from '@/config/pageRegistry';

/** Маршруты, несущие параметр в хэше (`#deal-quote/7`). */
export type ParameterisedPageId = 'product_detail' | 'request-detail' | 'deal-quote';

export type Page =
  | { type: Exclude<PageId, ParameterisedPageId> }
  | { type: 'product_detail'; productId: string }
  | { type: 'request-detail'; dealId: number }
  | { type: 'deal-quote'; dealId: number };

/**
 * Разобрать хэш обратно в `Page`, восстанавливая параметризованные маршруты
 * (`product_detail/<id>`), чтобы deep-link, обновление страницы и назад/вперёд работали.
 */
export function parseHashToPage(rawHash: string): Page {
  const hash = rawHash.replace(/^#/, '');
  // Отбрасываем query-хвост (например `crm-quotes?deal=123`) — страница читает свои
  // параметры сама; ТИП страницы должен быть голым маршрутом.
  const path = hash.split('?')[0];
  if (!path || path === 'dashboard') return { type: 'dashboard' };
  if (path.startsWith('product_detail/')) {
    return { type: 'product_detail', productId: path.slice('product_detail/'.length) } as Page;
  }
  if (path.startsWith('deal-quote/')) {
    const dealId = Number(path.slice('deal-quote/'.length));
    if (Number.isFinite(dealId) && dealId > 0) return { type: 'deal-quote', dealId };
    return { type: 'crm-deals' };
  }
  if (path === 'request-detail' || path.startsWith('request-detail/')) {
    const dealId = Number(path.slice('request-detail/'.length));
    if (Number.isFinite(dealId) && dealId > 0) return { type: 'request-detail', dealId };
    return { type: 'my-requests' };
  }
  return { type: path } as Page;
}

/** Хэш, соответствующий странице — обратная операция к `parseHashToPage`. */
export function pageToHash(page: Page): string {
  return page.type === 'product_detail'
    ? `product_detail/${(page as { productId: string }).productId}`
    : page.type;
}
