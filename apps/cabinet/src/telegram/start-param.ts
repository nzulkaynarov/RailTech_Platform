/**
 * Deep-link Mini App по `start_param` (кнопки бота CRM, M3-CRM-04; все объекты уведомлений — NOTIFY-2, J0): формат
 * `<сущность>_<целый id>` или одно слово раздела; всё остальное игнорируется (открывается главная). Те же адреса, что
 * `link` уведомлений колокольчика (`erp-portal.yaml`, `PortalNotification.link`):
 *
 * - `deal_<id>` — проект (сделка), `delivery_<id>` — поставки проекта (id сделки): `/deals/<id>`;
 * - `quote_<id>` — карточка КП;
 * - `invoice_<id>`, `act_<id>` — счёт и акт в своём разделе, строка выделена (`?focus=`);
 * - `product_<id>` — карточка «Моих товаров» партнёра (`?card=`), `products` — раздел целиком;
 * - `chat` — чат с менеджером (ADR-0023).
 */
const ID_ROUTES = new Map<string, (id: string) => string>(Object.entries({
  deal: (id: string) => `/deals/${id}`,
  delivery: (id: string) => `/deals/${id}`,
  quote: (id: string) => `/quotes/${id}`,
  invoice: (id: string) => `/invoices?focus=${id}`,
  act: (id: string) => `/acts?focus=${id}`,
  product: (id: string) => `/my-products?card=${id}`,
}));

const SECTION_ROUTES = new Map<string, string>([
  ['chat', '/messages'],
  ['products', '/my-products'],
  ['partner_app', '/company'],
  ['partner_contract', '/company'],
  ['company', '/company'],
  ['team', '/team'],
]);

const START_PARAM_RE = /^([a-z]+)_(\d{1,18})$/;

export function routeForStartParam(startParam: string | undefined | null): string | null {
  if (!startParam) return null;
  const section = SECTION_ROUTES.get(startParam);
  if (section) return section;
  const match = START_PARAM_RE.exec(startParam);
  const route = match ? ID_ROUTES.get(match[1]) : undefined;
  return match && route ? route(match[2]) : null;
}

/**
 * Начальный адрес Mini App: открытие корня с `start_param` сразу ведёт на цель deep-link.
 * Вызывается до создания маршрутизатора (main.tsx; тесты — для memory-router), поэтому
 * не зависит от повторных рендеров StrictMode и не мешает «Назад»/«Главная» потом.
 */
export function initialPath(pathname: string, startParam: string | undefined | null): string {
  if (pathname !== '/' && pathname !== '') return pathname;
  return routeForStartParam(startParam) ?? pathname;
}
