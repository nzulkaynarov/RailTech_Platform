import { type ReactNode, useEffect, useRef } from "react";
import { useSearchParams } from "react-router";

export interface DecisionCenterProps {
  /** Прежняя вкладка бокового окна (`?tab=approve`): старые ссылки очереди, колокольчика и писем несут её */
  legacyTab: string;
  /** Прежний лист телефона (`?sheet=approve`) */
  legacySheet: string;
  /** Имя блока для скринридера */
  label: string;
  children: ReactNode;
}

/**
 * Форма решения в центре карточки (ЕД-7): оплата, согласование, одобрение, резолюция — действие объекта, а не сведение, и
 * на телефоне до неё не нужно открывать окно. Ссылки со старой вкладкой (`?panel=open&tab=agree`, `?sheet=agree`) попадают
 * сюда же: параметры окна снимаются, а блок прокручивается в поле зрения.
 */
export function DecisionCenter({ legacyTab, legacySheet, label, children }: DecisionCenterProps) {
  const [params, setParams] = useSearchParams();
  const ref = useRef<HTMLElement>(null);
  const legacy = params.get("tab") === legacyTab || params.get("sheet") === legacySheet;
  useEffect(() => {
    if (!legacy) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (next.get("tab") === legacyTab) {
          next.delete("tab");
          next.delete("panel");
        }
        if (next.get("sheet") === legacySheet) next.delete("sheet");
        return next;
      },
      { replace: true },
    );
    ref.current?.scrollIntoView({ block: "start" });
  }, [legacy, legacyTab, legacySheet, setParams]);
  return (
    <section ref={ref} className="pf-dec-center" aria-label={label}>
      {children}
    </section>
  );
}
