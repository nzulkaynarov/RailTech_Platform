import { useSyncExternalStore } from "react";

/**
 * «Скрыть до завтра» баннер настройки (W15-H4, UX-оценка §5 P1-6): до начала следующих суток по часам браузера; утром
 * баннер возвращается сам, а в мастере есть «Вернуть баннер». Запоминается в браузере администратора (`localStorage`, по
 * его id): это удобство одного браузера, а не данные. Хранилище недоступно — скрыт до перезагрузки. Старое значение
 * «скрыт навсегда» (`"1"`, до W15-H4) считается истёкшим.
 */
const PREFIX = "rt-pf-setup-banner-hidden:";
const EVENT = "rt-pf-setup-banner";
const inMemory = new Map<string, number>();

/** Начало следующих суток по местному времени браузера */
export function startOfTomorrow(now: Date = new Date()): number {
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  return next.getTime();
}

function storedUntil(userId: string): number {
  const memory = inMemory.get(userId);
  if (memory !== undefined) return memory;
  try {
    const raw = window.localStorage.getItem(PREFIX + userId);
    const until = raw === null ? 0 : Number(raw);
    // «1» — прежнее «навсегда»: время в прошлом, баннер возвращается.
    return Number.isFinite(until) ? until : 0;
  } catch {
    return 0;
  }
}

export function isBannerHidden(userId: string, now: number = Date.now()): boolean {
  return storedUntil(userId) > now;
}

function notify(): void {
  window.dispatchEvent(new Event(EVENT));
}

export function hideBanner(userId: string, now: Date = new Date()): void {
  const until = startOfTomorrow(now);
  inMemory.set(userId, until);
  try {
    window.localStorage.setItem(PREFIX + userId, String(until));
  } catch {
    // Останется скрытым до перезагрузки страницы.
  }
  notify();
}

export function resetBannerHidden(userId: string): void {
  inMemory.set(userId, 0);
  try {
    window.localStorage.removeItem(PREFIX + userId);
  } catch {
    // Нечего очищать.
  }
  notify();
}

function subscribe(callback: () => void): () => void {
  window.addEventListener(EVENT, callback);
  return () => {
    window.removeEventListener(EVENT, callback);
  };
}

/** Скрыт ли баннер сейчас; баннер и мастер видят одно и то же состояние без перезагрузки. */
export function useBannerHidden(userId: string): boolean {
  return useSyncExternalStore(subscribe, () => isBannerHidden(userId));
}
