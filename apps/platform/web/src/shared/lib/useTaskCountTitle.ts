import { useEffect } from "react";

/** Максимум в бейдже и в заголовке: больше — «99+». */
export const COUNT_CAP = 99;

export function countLabel(count: number): string {
  return count > COUNT_CAP ? `${String(COUNT_CAP)}+` : String(count);
}

// Пробел после скобки необязателен: браузер срезает пробелы по краям заголовка, и «(5) » читается как «(5)».
const PREFIX = /^\(\d+\+?\)(?: |$)/;

/** Заголовок без числа задач: страницы пишут `document.title` сами, число добавляет только эта функция. */
export function stripCount(title: string): string {
  return title.replace(PREFIX, "");
}

/**
 * Заголовок с числом задач. Пустой заголовок (страница его ещё не задала) даёт «(5)» без хвостового пробела: иначе
 * записанное «(5) » браузер вернёт как «(5)», сравнение не сойдётся, и наблюдатель будет дописывать префикс бесконечно.
 */
export function titleWithCount(title: string, count: number): string {
  const base = stripCount(title).trim();
  if (count <= 0) return base;
  const mark = `(${countLabel(count)})`;
  return base ? `${mark} ${base}` : mark;
}

// Один наблюдатель и одно число на всё приложение. Если хук вызван в двух местах сразу (две оболочки в одном документе —
// так бывает в тестах), отдельные наблюдатели с разными числами переписывали бы заголовок друг за другом бесконечно.
let current = 0;
let users = 0;
let observer: MutationObserver | null = null;

function apply(): void {
  const wanted = titleWithCount(document.title, current);
  if (document.title !== wanted) document.title = wanted;
}

function watch(): void {
  if (observer) return;
  const node = document.head.querySelector("title");
  if (!node) return;
  observer = new MutationObserver(apply);
  observer.observe(node, { childList: true, characterData: true, subtree: true });
}

/**
 * Число задач «Главной» в заголовке вкладки: «(5) Задачи — RailTech» (ГЛ-2). Страницы меняют заголовок при
 * каждом переходе (`useDocumentTitle`), поэтому префикс держит наблюдатель за `<title>`; 0 — префикса нет.
 * Действует число того, кто вызвал хук последним.
 */
export function useTaskCountTitle(count: number): void {
  useEffect(() => {
    users += 1;
    return () => {
      users -= 1;
      if (users > 0) return;
      observer?.disconnect();
      observer = null;
      current = 0;
      document.title = stripCount(document.title);
    };
  }, []);
  useEffect(() => {
    current = count;
    apply();
    watch();
  }, [count]);
}
