/** Экран «Состояние системы» (аудит 2026-10-12 §3 п. 6). */
export const system = {
  system: {
    refresh: "Проверить снова",
    checkedAt: "проверено {ago}",
    neverChecked: "ещё не проверялось",
    status: {
      ok: "В норме",
      warn: "Внимание",
      fail: "Сбой",
      unknown: "Нет данных",
    } as Record<string, string>,
    hint: "Модели проверяет монитор раз в час — эта страница их не вызывает и денег не тратит.",
  },
};
