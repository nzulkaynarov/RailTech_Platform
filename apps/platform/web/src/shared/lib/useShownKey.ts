import { useState } from "react";

/**
 * Значение, к которому относятся данные на экране (UX-1c, S8): пока видны прежние строки (`placeholder`) — прежнее,
 * пришли данные с новыми условиями (или взяты из кэша сразу) — новое. Так колонки и подписи списка (например, колонка
 * «Ответственный» в реестре «Все») меняются вместе со строками, а не раньше них.
 */
export function useShownValue<T>(
  value: T,
  placeholder: boolean,
  same: (a: T, b: T) => boolean = Object.is,
): T {
  const [shown, setShown] = useState(value);
  if (!placeholder && !same(shown, value)) setShown(value);
  return placeholder ? shown : value;
}

/**
 * Ключ данных, которые сейчас на экране (UX-1c, S8). `DataBlock` по смене ключа перестраивает список целиком, а не
 * двигает строки, совпавшие у старого и нового ответа: при смене фильтра строки не «едут» на новые места. Перезапрос тех
 * же условий (после действия, опрос) ключ не меняет — фокус и состояние строк сохраняются.
 */
export function useShownKey(queryKey: unknown, placeholder: boolean): string {
  return useShownValue(JSON.stringify(queryKey ?? null), placeholder);
}

/**
 * Последнее известное значение (UX-1c, S8): пока ответа нет (перезапрос с другими условиями), видно прежнее — числа на
 * вкладках не пропадают и не меняют ширину вкладок.
 */
export function useLastDefined<T>(value: T | undefined): T | undefined {
  const [last, setLast] = useState(value);
  if (value !== undefined && !Object.is(value, last)) setLast(value);
  return value ?? last;
}
