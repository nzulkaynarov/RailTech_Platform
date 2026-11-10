import { App } from "antd";
import { useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

export interface ConfirmActionOptions {
  /** Глагол действия, как на кнопке: «Подписать» */
  action: string;
  /** Что именно: номер или название объекта */
  object: string;
  /** Суть объекта одной строкой: контрагент, сумма */
  summary?: ReactNode;
  danger?: boolean;
  onConfirm: () => void;
}

/** Окно подтверждения необратимого или дорогого действия (CONVENTIONS Платформы §2 п. 8). */
export function useConfirmAction(): (options: ConfirmActionOptions) => void {
  const { modal } = App.useApp();
  const { t } = useTranslation("ui");
  const open = useRef(false);
  return ({ action, object, summary, danger, onConfirm }) => {
    // Двойное нажатие не открывает второе окно
    if (open.current) return;
    open.current = true;
    modal.confirm({
      afterClose: () => {
        open.current = false;
      },
      title: `${`${action} ${object}`.trim()}?`,
      content: summary,
      icon: null,
      okText: action,
      cancelText: t("confirm.cancel"),
      okButtonProps: danger ? { danger: true } : {},
      onOk: onConfirm,
    });
  };
}

/** Подпись кнопки без хвоста о следующем шаге: «Одобрить КП → отправить клиенту» → «Одобрить КП». */
export function shortAction(label: string): string {
  return label.split(" → ")[0] ?? label;
}
