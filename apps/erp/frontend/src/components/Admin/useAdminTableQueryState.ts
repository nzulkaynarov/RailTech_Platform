/**
 * Состояние админ-таблицы (поиск/фильтры/страница) в localStorage. Отдельный модуль:
 * файл-компонент с экспортированным хуком ломает Fast Refresh.
 */

import { useUrlState } from '@/hooks/useUrlState';

const QP_KEYS = {
  search: 'q',
  tab: 'tab',
  sort: 'sort',
  page: 'page',
} as const;

export function useAdminTableQueryState(storageKey: string) {
  const urlState = useUrlState();
  const getParam = (k: keyof typeof QP_KEYS) => urlState.get(`${storageKey}.${QP_KEYS[k]}`);
  return {
    search: getParam('search'),
    tab: getParam('tab'),
    sort: getParam('sort'),
    page: Number(getParam('page') || '1') || 1,
  };
}
