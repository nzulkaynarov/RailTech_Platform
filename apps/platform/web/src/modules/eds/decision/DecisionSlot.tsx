import { Drawer } from "antd";
import { type ReactNode, useEffect } from "react";
import { useSearchParams } from "react-router";

import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useViewport } from "../../../app/shell/useViewport";

export interface DecisionSlotProps {
  /** Вкладка бокового окна каркаса (`approve`, `agree`) */
  tab: string;
  /** Имя листа в адресе: `?sheet=<sheet>` */
  sheet: string;
  /** Заголовок листа на телефоне */
  title: ReactNode;
  /** Имя листа для скринридера и слово кнопки «Закрыть» */
  label: string;
  closeLabel: string;
  /** Содержимое: окно справа или лист; на листе кнопки решения закреплены внизу, после решения лист закрывается */
  children: (variant: "panel" | "sheet", onDone: (() => void) | undefined) => ReactNode;
}

/**
 * Где живёт форма решения. Широкий и средний экран — вкладка бокового окна каркаса. Телефон (< 768 px) — полноэкранный лист
 * с кнопками внизу (директор решает с телефона, UX P0-4): открывается параметром `?sheet=<sheet>`; ссылки из очереди и
 * колокольчика с `panel=open` на телефоне переводятся в лист, чтобы рядом не открывалось окно каркаса.
 */
export function DecisionSlot({
  tab,
  sheet,
  title,
  label,
  closeLabel,
  children,
}: DecisionSlotProps) {
  const { mobile } = useViewport();
  const [params, setParams] = useSearchParams();
  const sheetOpen = params.get("sheet") === sheet;
  const wantsPanel = params.get("panel") === "open";

  useEffect(() => {
    if (!mobile || !wantsPanel) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("panel");
        next.set("sheet", sheet);
        return next;
      },
      { replace: true },
    );
  }, [mobile, wantsPanel, setParams, sheet]);

  if (!mobile) return <PanelPortal tab={tab}>{children("panel", undefined)}</PanelPortal>;

  const close = () => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("sheet");
        return next;
      },
      { replace: true },
    );
  };
  return (
    <Drawer
      open={sheetOpen}
      onClose={close}
      placement="bottom"
      height="100%"
      destroyOnHidden
      title={title}
      closeIcon={null}
      extra={
        <button type="button" className="pf-dec-close pf-focusable" onClick={close}>
          {closeLabel}
        </button>
      }
      styles={{ body: { padding: 16 }, header: { padding: "12px 16px" } }}
      aria-label={label}
      className="pf-dec-sheet"
    >
      {children("sheet", close)}
    </Drawer>
  );
}
