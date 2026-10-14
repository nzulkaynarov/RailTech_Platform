/**
 * Deep-link Mini App по `start_param` (кнопки бота CRM, M3-CRM-04): `deal_<id>` открывает сделку,
 * `quote_<id>` — КП. Формат `<сущность>_<целый id>`; всё остальное игнорируется (открывается главная).
 */
const START_PARAM_ROUTES: Record<string, string> = {
  deal: '/deals',
  quote: '/quotes',
};

const START_PARAM_RE = /^([a-z]+)_(\d{1,18})$/;

export function routeForStartParam(startParam: string | undefined | null): string | null {
  if (!startParam) return null;
  const match = START_PARAM_RE.exec(startParam);
  if (!match) return null;
  const base = START_PARAM_ROUTES[match[1]];
  return base ? `${base}/${match[2]}` : null;
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
