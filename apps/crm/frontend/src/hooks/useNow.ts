import { useEffect, useState } from "react";

/**
 * Текущее время, обновляемое раз в `intervalMs` — для таймеров ожидания во «Входящих».
 * Это только перерисовка на клиенте, запросов к серверу нет (данные обновляет SSE).
 */
export function useNow(intervalMs = 30_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(new Date());
    }, intervalMs);
    return () => {
      clearInterval(timer);
    };
  }, [intervalMs]);
  return now;
}
