import { Button, Modal } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

/** Ширина окна по центру (стандарт интерфейса §6): вопрос подтверждения или 1–3 поля, без прокрутки. */
export const DIALOG_WIDTH = 448;

/**
 * Окно по центру — только для подтверждения или короткой формы на 1–3 поля (стандарт интерфейса §6); форма длиннее —
 * `FormSheet`. Ширина одна (448), закрытие по фону выключено, содержимое сбрасывается при закрытии.
 *
 * Подвал по умолчанию — «Отмена» и справа главная кнопка (`okLabel`, `onOk`); без `okLabel` — одна «Закрыть». Свой
 * подвал (`footer`) — когда кнопок действия несколько или они внутри формы окна; `footer={null}` — без подвала.
 */
export function Dialog({
  open = true,
  title,
  okLabel,
  onOk,
  okDisabled = false,
  loading = false,
  danger = false,
  cancelLabel,
  footer,
  onCancel,
  children,
}: {
  open?: boolean;
  title?: ReactNode;
  okLabel?: string;
  onOk?: () => void;
  okDisabled?: boolean;
  loading?: boolean;
  /** Главная кнопка — опасное действие (удалить, отклонить, отозвать) */
  danger?: boolean;
  cancelLabel?: string;
  footer?: ReactNode;
  onCancel: () => void;
  children?: ReactNode;
}) {
  const { t } = useTranslation("ui");
  const buttons =
    footer !== undefined ? (
      footer
    ) : okLabel ? (
      <>
        <Button onClick={onCancel}>{cancelLabel ?? t("formSheet.cancel")}</Button>
        <Button
          type="primary"
          danger={danger}
          loading={loading}
          disabled={okDisabled}
          onClick={onOk}
        >
          {okLabel}
        </Button>
      </>
    ) : (
      <Button onClick={onCancel}>{cancelLabel ?? t("formSheet.close")}</Button>
    );
  return (
    <Modal
      open={open}
      title={title}
      width={DIALOG_WIDTH}
      onCancel={onCancel}
      destroyOnHidden
      maskClosable={false}
      footer={buttons}
    >
      {children}
    </Modal>
  );
}
