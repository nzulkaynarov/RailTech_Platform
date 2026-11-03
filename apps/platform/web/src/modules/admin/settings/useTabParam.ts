import { useSearchParams } from "react-router";

/**
 * Вкладка страницы Настроек в адресе `?tab=` (один уровень вкладок на странице — SET-IA, без вкладок во вкладках).
 * Неизвестное значение — первая вкладка; смена вкладки не копит историю и сбрасывает параметры прежней вкладки, кроме окна.
 */
export function useTabParam<T extends string>(tabs: readonly T[]): [T, (next: string) => void] {
  const [params, setParams] = useSearchParams();
  const asked = params.get("tab");
  const first = tabs[0] as T;
  const active = tabs.find((tab) => tab === asked) ?? first;
  const select = (next: string) => {
    setParams(
      (prev) => {
        const out = new URLSearchParams();
        if (next !== first) out.set("tab", next);
        const panel = prev.get("panel");
        if (panel) out.set("panel", panel);
        return out;
      },
      { replace: true },
    );
  };
  return [active, select];
}
