import { useCallback } from "react";

import { useProducts } from "../api/adminQueries";
import { t } from "../i18n/ru";

/**
 * Название продукта по ключу (`rail-tracking` → «RT-Track»): справочник продуктов базы
 * знаний. Пока справочник грузится или ключа в нём нет — ключ как есть.
 */
export function useProductNames(): (key: string | null | undefined) => string {
  const { data } = useProducts();
  return useCallback(
    (key) => {
      if (!key) return t.common.none;
      return data?.find((p) => p.key === key)?.name ?? key;
    },
    [data],
  );
}
