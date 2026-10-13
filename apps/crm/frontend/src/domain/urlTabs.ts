/**
 * Вкладка страницы в адресе (`?tab=`), чтобы ссылкой можно было поделиться и «Назад» возвращал
 * туда же (UX волна 3: карточка клиента, «Подключения»). Неизвестная или недоступная вкладка —
 * первая доступная.
 */
export function resolveTab<T extends string>(requested: string | null, available: readonly T[]): T {
  const found = available.find((tab) => tab === requested);
  if (found !== undefined) return found;
  const first = available[0];
  if (first === undefined) throw new Error("no tabs available");
  return first;
}
