import { useEffect } from "react";

const PREFIX = "rt-pf-queue-cards:";
/** Пока не знаем, сколько счётчиков у сотрудника: одна строка сетки на широком экране. */
const DEFAULT_COUNT = 4;

function stored(userId: string): number {
  try {
    const raw = window.localStorage.getItem(PREFIX + userId);
    const value = raw === null ? Number.NaN : Number(raw);
    return Number.isInteger(value) && value >= 0 && value <= 12 ? value : DEFAULT_COUNT;
  } catch {
    return DEFAULT_COUNT;
  }
}

/**
 * Сколько карточек-счётчиков рисовать до ответа «Моих задач» (UX-1c, аудит 2026-10-30, S10): столько, сколько было в прошлый
 * раз в этом браузере (`localStorage` — удобство одного браузера, не данные), а впервые — четыре. Пришёл ответ — число
 * запоминается. У администратора без счётчиков после первого раза скелетона нет вовсе.
 */
export function useCardsCount(userId: string, known: number | undefined): number {
  useEffect(() => {
    if (known === undefined) return;
    try {
      window.localStorage.setItem(PREFIX + userId, String(known));
    } catch {
      // Без хранилища — снова четыре в следующий раз.
    }
  }, [userId, known]);
  return known ?? stored(userId);
}
