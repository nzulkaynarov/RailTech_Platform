import { Drawer } from "antd";
import type { ReactNode } from "react";

import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useViewport } from "../../../app/shell/useViewport";

/**
 * Карточка лида, клиента и форма «Создать заявку» — в боковом окне каркаса (SPEC-v3 §7.2); на телефоне (< 768) —
 * полноэкранный лист с кнопками внизу (как карточка документа EDS). Закрыть лист — кнопкой внутри или Esc.
 */
export function Sheet({
  label,
  onClose,
  children,
}: {
  label: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const { mobile } = useViewport();
  if (mobile) {
    return (
      <Drawer
        open
        placement="bottom"
        height="100dvh"
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
  return <PanelPortal tab="card">{children}</PanelPortal>;
}
