/**
 * Хэш-маршрутизация SPA (ADR: React Router не используется).
 *
 * Тип `Page` выводится из реестра страниц, поэтому список маршрутов не приходится
 * поддерживать дважды. Отдельно перечислены только параметризованные маршруты —
 * те, что несут в хэше идентификатор.
 */

import type { PageId } from '@/config/pageRegistry';

/** Маршруты, несущие параметр в хэше (`#deal-quote/7`). */
export type ParameterisedPageId = 'product_detail' | 'product-edit' | 'request-detail' | 'deal-quote';

export type Page =
  | { type: Exclude<PageId, ParameterisedPageId> }
  | { type: 'product_detail'; productId: string }
  | { type: 'product-edit'; productId: string }
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
  // Редактор карточки (R3). Голый `#product-edit` без id — откат в реестр, не сломанный экран.
  if (path === 'product-edit' || path.startsWith('product-edit/')) {
    const productId = path.slice('product-edit/'.length);
    if (productId) return { type: 'product-edit', productId } as Page;
    return { type: 'my-products' } as Page;
  }
  // Голая форма (`#deal-quote` без номера) обрабатывается наравне с `deal-quote/abc`:
  // раньше она проваливалась в общий `return { type: path }` и рендерила билдер КП с
  // `dealId: undefined` — сломанный экран вместо отката на список сделок.
  if (path === 'deal-quote' || path.startsWith('deal-quote/')) {
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

/**
 * Хэш, соответствующий странице — ТОЧНАЯ обратная операция к `parseHashToPage`.
 *
 * Раньше идентификатор подставлялся только для `product_detail`, а `request-detail` и
 * `deal-quote` уходили в историю голыми. Назад/вперёд это не ломало (страница едет в
 * `history.state`), но URL переставал описывать экран: обновление страницы, закладка или
 * ссылка, отправленная коллеге, уводили с карточки сделки на список заявок. Прямые
 * присвоения `window.location.hash` (корзина, очередь согласования, уведомления) номер
 * всегда клали — расходился именно этот путь.
 */
export function pageToHash(page: Page): string {
  switch (page.type) {
    case 'product_detail':
      return `product_detail/${page.productId}`;
    case 'product-edit':
      return `product-edit/${page.productId}`;
    case 'request-detail':
      return `request-detail/${page.dealId}`;
    case 'deal-quote':
      return `deal-quote/${page.dealId}`;
    default:
      return page.type;
  }
}
