import { Drawer } from "antd";
import type { ReactNode } from "react";

import { PanelPortal } from "../../app/shell/PanelSlot";
import { useViewport } from "../../app/shell/useViewport";
import { useKeyboardInset } from "./useKeyboardInset";

/**
 * Карточка лида, клиента и форма «Создать заявку» — в боковом окне каркаса (SPEC-v3 §7.2); на телефоне (< 768) —
 * полноэкранный лист с кнопками внизу (как карточка документа EDS). Закрыть лист — кнопкой внутри или Esc.
 */
export function Sheet({
  label,
  onClose,
  children,
  tab = "card",
  over = false,
}: {
  label: string;
  onClose: () => void;
  children: ReactNode;
  /** Форма поверх карточки объекта: карточка скрыта, пока форма открыта */
  over?: boolean;
  /** Вкладка бокового окна раздела (у расчёта — `task`, у остальных — `card`) */
  tab?: string;
}) {
  const { mobile } = useViewport();
  useKeyboardInset();
  if (mobile) {
    return (
      <Drawer
        open
        placement="bottom"
        height="100dvh" /* shrinks above the keyboard: styles/touch.css */
        closable={false}
        keyboard
        onClose={onClose}
        title={label}
        styles={{ body: { padding: 16 } }}
        rootClassName="pf-crm-sheet"
      >
        {children}
      </Drawer>
    );
  }
  return (
    <PanelPortal tab={tab} over={over}>
      {children}
    </PanelPortal>
  );
}
