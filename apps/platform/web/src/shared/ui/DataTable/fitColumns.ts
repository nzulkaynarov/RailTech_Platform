/**
 * Какие столбцы скрыть, чтобы таблица поместилась в рамку шириной `avail` (0 — ширина ещё неизвестна: ничего не прячем).
 * Прячем по одному: сначала с наибольшим `priority`, при равенстве — правый. Столбцы без приоритета не трогаем.
 */
export function fitHidden(
  ids: readonly string[],
  widthOf: (id: string) => number,
  priorityOf: (id: string) => number,
  avail: number,
): string[] {
  if (avail <= 0) return [];
  const left = [...ids];
  const out: string[] = [];
  const total = () => left.reduce((sum, id) => sum + widthOf(id), 0);
  while (total() > avail) {
    let pick = -1;
    left.forEach((id, index) => {
      const p = priorityOf(id);
      if (p > 0 && (pick < 0 || p >= priorityOf(left[pick] ?? ""))) pick = index;
    });
    if (pick < 0) break;
    out.push(...left.splice(pick, 1));
  }
  return out;
}
