import { useEffect } from "react";

/** Максимум в бейдже и в заголовке: больше — «99+». */
export const COUNT_CAP = 99;

export function countLabel(count: number): string {
  return count > COUNT_CAP ? `${String(COUNT_CAP)}+` : String(count);
}

const PREFIX = /^\(\d+\+?\) /;

/** Заголовок без числа задач: страницы пишут `document.title` сами, число добавляет только эта функция. */
export function stripCount(title: string): string {
  return title.replace(PREFIX, "");
}

/**
 * Число задач «Главной» в заголовке вкладки: «(5) Задачи — RailTech» (ГЛ-2). Страницы меняют заголовок при
 * каждом переходе (`useDocumentTitle`), поэтому префикс держит наблюдатель за `<title>`; 0 — префикса нет.
 */
export function useTaskCountTitle(count: number): void {
  useEffect(() => {
    const prefix = count > 0 ? `(${countLabel(count)}) ` : "";
    const apply = () => {
      const wanted = prefix + stripCount(document.title);
      if (document.title !== wanted) document.title = wanted;
    };
    apply();
    const node = document.head.querySelector("title");
    if (!node) return undefined;
    const observer = new MutationObserver(apply);
    observer.observe(node, { childList: true, characterData: true, subtree: true });
    return () => {
      observer.disconnect();
      document.title = stripCount(document.title);
    };
  }, [count]);
}
