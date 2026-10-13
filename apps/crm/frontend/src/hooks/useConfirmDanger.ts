import { App as AntApp } from "antd";

import { t } from "../i18n/ru";

type Options = { title: string; content?: string; okText: string; onOk: () => unknown };

/**
 * Подтверждение необратимого, видимого клиенту или чужого действия (аудит UI U-04):
 * красная кнопка с глаголом действия и объяснением последствий.
 */
export function useConfirmDanger() {
  const { modal } = AntApp.useApp();
  return ({ title, content, okText, onOk }: Options) => {
    void modal.confirm({
      title,
      content,
      okText,
      cancelText: t.actions.cancel,
      okButtonProps: { danger: true },
      onOk: () => Promise.resolve(onOk()),
    });
  };
}
