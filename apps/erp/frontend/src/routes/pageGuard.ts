/**
 * Единое решение о доступе к странице.
 *
 * ERP — бэк-офис одной компании (M1-ERP-02 волна 3): контекста «покупатель / продавец» и
 * переключения на страницу «другой стороны» больше нет. Страницу открывает любой сотрудник;
 * действия на ней ограничивает право роли (истина — на сервере, меню прячет недоступное —
 * `config/navigation`). Гейт остался ровно для одного: устаревший или неизвестный хэш
 * (`#my-requests` из старой закладки, `#admin-*`) уводится на дашборд с объяснением, а не
 * рендерит дашборд под чужим адресом.
 */

import { PAGE_IDS } from '@/config/pageRegistry';

const KNOWN_PAGES: ReadonlySet<string> = new Set(PAGE_IDS);

export type PageGuardDecision =
  | { action: 'allow' }
  | { action: 'bounce'; reason: 'unknown' };

export function evaluatePageGuard(pageType: string): PageGuardDecision {
  return KNOWN_PAGES.has(pageType) ? { action: 'allow' } : { action: 'bounce', reason: 'unknown' };
}
