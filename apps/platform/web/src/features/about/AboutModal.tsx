import { Modal } from "antd";
import { useTranslation } from "react-i18next";

import { AboutPanel } from "./AboutPanel";

export interface AboutModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Окно «О системе» (W-REL, UX/UI shell optimization):
 * Компактный Modal (width=420) с метаданными релиза, статусом сервисов и данными поддержки.
 */
export function AboutModal({ open, onClose }: AboutModalProps) {
  const { t } = useTranslation("help");

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={420}
      aria-label={t("about.title")}
      destroyOnHidden
    >
      <AboutPanel />
    </Modal>
  );
}
