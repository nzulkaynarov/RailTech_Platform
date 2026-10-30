import { type ReactNode, useCallback, useContext, useLayoutEffect, useMemo, useState } from "react";
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

/**
 * Для страницы: содержимое вкладки `tab` бокового окна. Вкладка не активна — ничего не рисуется.
 *
 * Портал рисует в свой постоянный узел, а узел переносится в текущий элемент окна (R3-D-4). При смене ширины каркас
 * меняет колонку справа на Drawer (и обратно) — элемент окна другой, а иногда на миг его нет; портал прямо в элемент окна
 * пересоздал бы содержимое и потерял несохранённое (форму приглашения, подтверждение удаления роли). С постоянным узлом
 * дерево страницы не пересоздаётся: пока окна нет (закрыто, перестраивается), узел просто отсоединён от документа.
 */
export function PanelPortal({ tab, children }: { tab: string; children: ReactNode }) {
  const slot = useContext(PanelSlotContext);
  const claim = slot?.claim;
  // До отрисовки (S12): окно наполняется в том же кадре, без промежуточного пустого состояния каркаса.
  useLayoutEffect(() => claim?.(tab), [claim, tab]);
  const [host] = useState(() => document.createElement("div"));
  const target = slot?.tab === tab ? slot.element : null;
  useLayoutEffect(() => {
    if (!target) return;
    target.appendChild(host);
    return () => {
      if (host.parentNode === target) target.removeChild(host);
    };
  }, [target, host]);
  if (!slot || slot.tab !== tab) return null;
  return createPortal(children, host);
}
