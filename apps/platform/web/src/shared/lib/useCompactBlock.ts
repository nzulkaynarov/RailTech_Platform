import { useLayoutEffect, useRef, useState } from "react";

/** Запас порога «список → таблица» (UX-1a, аудит S3): у самой границы вид не мигает туда-обратно. */
export const COMPACT_HYSTERESIS = 40;

/**
 * Таблица или список — по ширине самого блока, а не экрана: с открытым боковым окном рядом для таблицы может быть тесно.
 * В список — когда блок уже `minWidth`; обратно в таблицу — только когда он шире `minWidth + 40`. Первый замер — до
 * отрисовки (`useLayoutEffect`), чтобы таблица не мелькала перед списком. Пока замера нет (jsdom, блок не в документе) —
 * `fallback`.
 */
export function useCompactBlock<T extends HTMLElement = HTMLDivElement>(
  minWidth: number,
  fallback: boolean,
) {
  const ref = useRef<T>(null);
  const [compact, setCompact] = useState<boolean | null>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const decide = (width: number) => {
      if (width <= 0) return;
      setCompact((prev) =>
        prev === true ? width < minWidth + COMPACT_HYSTERESIS : width < minWidth,
      );
    };
    decide(element.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      decide(entry?.contentRect.width ?? 0);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [minWidth]);
  return { ref, compact: compact ?? fallback };
}
