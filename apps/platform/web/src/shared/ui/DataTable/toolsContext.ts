import { createContext, useContext } from "react";

export interface ToolsValue {
  target: HTMLElement | null;
  setTarget: (element: HTMLElement | null) => void;
}

/** Место кнопки «Столбцы» в строке фильтров экрана (см. `RegistryTools.tsx`). */
export const ToolsContext = createContext<ToolsValue | null>(null);

/** Для `DataTable`: место «Столбцов» в строке фильтров; `undefined` — экран его не объявил (кнопка над таблицей). */
export function useToolsTarget(): HTMLElement | undefined {
  return useContext(ToolsContext)?.target ?? undefined;
}
