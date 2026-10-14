import type { CatalogItem } from '@/api/portal';

/**
 * Каталог: страница — 12 карточек (две «полки» по 6 на десктопе, удобная прокрутка на телефоне).
 *
 * Категории (QUESTIONS Q-15): контракт принимает фильтр `category_id`, но не отдаёт ни id категории в
 * `CatalogItem`, ни справочника категорий — фильтровать по id нечем. До ответа ERP Cabinet строит
 * категории из названий (`category`) первой сотни опубликованных позиций, а выбранную категорию
 * фильтрует на клиенте по выборке до 100 позиций (`page_size` max). Ограничение известно и записано.
 */
export const CATALOG_PAGE_SIZE = 12;
export const CATALOG_MAX_PAGE_SIZE = 100;

export function distinctCategories(items: CatalogItem[], language: string): string[] {
  const names = new Set<string>();
  for (const item of items) if (item.category) names.add(item.category);
  return Array.from(names).sort((a, b) => a.localeCompare(b, language));
}

export function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

/** Номер страницы из URL: целое ≥ 1, иначе 1. */
export function parsePage(value: string | null): number {
  const page = Number(value);
  return Number.isInteger(page) && page >= 1 ? page : 1;
}
