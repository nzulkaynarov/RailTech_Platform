import { useContext, useMemo, useState, type ReactNode } from "react";

import { ToolsContext } from "./toolsContext";
import "./data-table.css";

/**
 * Реестр по стандарту интерфейса §9: фильтры и «Столбцы» таблицы стоят в одной строке. Обёртка `RegistryTools` одна на
 * приложение (каркас); экран кладёт в свою строку фильтров `ToolsSlot` — и `DataTable` этого экрана ставит туда кнопку
 * «Столбцы» вместо отдельной полосы над таблицей. Экран без `ToolsSlot` ведёт себя как прежде.
 */
export function RegistryTools({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const value = useMemo(() => ({ target, setTarget }), [target]);
  return <ToolsContext.Provider value={value}>{children}</ToolsContext.Provider>;
}

/** Место кнопки «Столбцы» в строке фильтров: прижато к правому краю строки. */
export function ToolsSlot() {
  const tools = useContext(ToolsContext);
  return <div className="pf-tools-slot" ref={tools?.setTarget} />;
}
