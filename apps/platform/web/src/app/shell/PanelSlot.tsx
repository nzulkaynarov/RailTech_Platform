import { type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { PanelSlotContext } from "./panelSlotContext";

/**
 * Содержимое бокового окна от страницы раздела (PLT-15). Каркас рисует `<div ref>` в активной вкладке и пустое состояние,
 * пока ни одна страница не заняла вкладку; страница кладёт свою разметку через `PanelPortal` — она остаётся в дереве
 * страницы (её контекст, состояние форм), а на экране оказывается внутри окна. Так страницы не знают про `AppShell`,
 * а `AppShell` — про страницы.
 */
export function PanelSlotProvider({ children }: { children: ReactNode }) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [claimed, setClaimed] = useState<readonly string[]>([]);
  const [tab, setTab] = useState("card");
  const claim = useCallback((name: string) => {
    setClaimed((prev) => [...prev, name]);
    return () => {
      setClaimed((prev) => {
        const index = prev.indexOf(name);
        return index < 0 ? prev : [...prev.slice(0, index), ...prev.slice(index + 1)];
      });
    };
  }, []);
  const value = useMemo(
    () => ({ element, setElement, claimed, claim, tab, setTab }),
    [element, claimed, claim, tab],
  );
  return <PanelSlotContext.Provider value={value}>{children}</PanelSlotContext.Provider>;
}

/** Для страницы: содержимое вкладки `tab` бокового окна. Вкладка не активна или окно закрыто — ничего не рисуется. */
export function PanelPortal({ tab, children }: { tab: string; children: ReactNode }) {
  const slot = useContext(PanelSlotContext);
  const claim = slot?.claim;
  useEffect(() => claim?.(tab), [claim, tab]);
  if (!slot?.element || slot.tab !== tab) return null;
  return createPortal(children, slot.element);
}
