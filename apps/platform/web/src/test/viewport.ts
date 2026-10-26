type Change = (event: { matches: boolean; media: string }) => void;

/** Подписчики `change` media queries (слушатель → его запрос): смена ширины будит их, как браузер при сужении окна. */
const listeners = new Map<Change, string>();

function matchesAt(width: number, query: string): boolean {
  const min = /\(min-width:\s*(\d+)px\)/.exec(query);
  return min ? width >= Number(min[1]) : false;
}

/**
 * jsdom не считает media queries: тест задаёт ширину окна, а `matchMedia` отвечает на `(min-width: Npx)`. Смена ширины
 * посреди теста оповещает подписчиков (`useViewport`, адаптивность antd) — каркас перестраивается, как в браузере.
 */
export function setViewportWidth(width: number): void {
  Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: width });
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: matchesAt(width, query),
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: (_type: string, listener: Change) => {
        listeners.set(listener, query);
      },
      removeEventListener: (_type: string, listener: Change) => {
        listeners.delete(listener);
      },
      dispatchEvent: () => false,
    }),
  });
  for (const [listener, query] of [...listeners]) {
    listener({ matches: matchesAt(width, query), media: query });
  }
}
