import { Drawer } from "antd";
import { useSearchParams } from "react-router";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import { DocumentCard } from "./DocumentCard";

/**
 * Документ в боковом окне (SPEC-v3 §7.3: «Клик — документ в боковом окне»). На широком и среднем экране это окно каркаса
 * (колонка справа или Drawer 360 px), на телефоне (< 768) — полноэкранный лист с кнопками внизу.
 */
export function DocumentSheet({ id }: { id: string }) {
  const { t } = useTranslation("documents");
  const { mobile } = useViewport();
  const [, setParams] = useSearchParams();
  const close = () => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("doc");
        next.delete("panel");
        return next;
      },
      { replace: true },
    );
  };
  if (mobile) {
    return (
      <Drawer
        open
        placement="bottom"
        height="100dvh"
        closable={false}
        keyboard
        onClose={close}
        title={t("panel.label")}
        styles={{ body: { padding: 16 } }}
        rootClassName="pf-doc-sheet"
      >
        <DocumentCard key={id} id={id} sheet onClose={close} />
      </Drawer>
    );
  }
  return (
    <PanelPortal tab="card">
      <DocumentCard key={id} id={id} onClose={close} />
    </PanelPortal>
  );
}
