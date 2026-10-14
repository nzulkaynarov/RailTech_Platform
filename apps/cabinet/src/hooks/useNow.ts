import { useEffect, useState } from 'react';

/** Раз в минуту — достаточно для счётчиков «просрочено / осталось дней» и не будит рендер зря. */
const DEFAULT_TICK_MS = 60_000;

/**
 * Текущее время как ЗНАЧЕНИЕ, за которым компонент подписан следить.
 *
 * `Date.now()` прямо в рендере — нечистый вызов (`react-hooks/purity`): результат меняется
 * между рендерами, которые React вправе повторить, и при этом НЕ обновляется сам по себе.
 * На практике это давало замирающие счётчики: во вкладке, открытой с утра, «просроченные КП»
 * и «дней до конца подписки» показывали утреннее число, пока что-нибудь другое не вызовет
 * перерисовку.
 *
 * Здесь время живёт в состоянии и тикает по таймеру — чистый рендер и живой счётчик.
 * Интервал общий на компонент, а не на каждую строку списка: вызывать хук нужно один раз
 * наверху и передавать значение вниз.
 *
 * @example
 * const now = useNow();
 * const expired = quotes.filter((q) => new Date(q.valid_until).getTime() < now).length;
 */
export function useNow(tickMs: number = DEFAULT_TICK_MS): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (tickMs <= 0) return;
    const timer = window.setInterval(() => setNow(Date.now()), tickMs);
    return () => window.clearInterval(timer);
  }, [tickMs]);

  return now;
}
