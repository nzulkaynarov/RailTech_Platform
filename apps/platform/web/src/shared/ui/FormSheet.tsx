import { App, Button } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Sheet } from "./Sheet";
import "./form-parts.css";

/**
 * Форма на 4–15 полей или карточка объекта — в боковой панели (стандарт интерфейса §6): заголовок сверху, поля в одну
 * колонку, подвал закреплён — «Отмена» и справа главная кнопка, связанная с формой атрибутом `form`. Изменённую форму
 * (`dirty`) нельзя закрыть молча: «Отмена» спрашивает, выйти ли без сохранения. Сама форма (`formId`) — у вызывающего.
 * На телефоне — лист на весь экран (`Sheet`).
 */
export function FormSheet({
  title,
  formId,
  submitLabel,
  saving,
  error,
  dirty = false,
  readOnly = false,
  onCancel,
  children,
}: {
  title: string;
  formId: string;
  submitLabel: string;
  saving: boolean;
  /** Ошибка без своего поля — над полями; ошибки полей стоят под полями */
  error?: ReactNode;
  /** В форме есть несохранённые изменения */
  dirty?: boolean;
  /** Просмотр без права на изменение: вместо «Отмена» и главной кнопки — «Закрыть» */
  readOnly?: boolean;
  onCancel: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation("ui");
  const { modal } = App.useApp();
  const close = () => {
    if (!dirty || readOnly) {
      onCancel();
      return;
    }
    modal.confirm({
      title: t("unsavedGuard.title"),
      content: t("unsavedGuard.text"),
      okText: t("unsavedGuard.leave"),
      cancelText: t("unsavedGuard.stay"),
      okButtonProps: { danger: true },
      onOk: onCancel,
    });
  };
  return (
    <Sheet label={title} onClose={close}>
      <section className="pf-fsheet" aria-labelledby={`${formId}-title`}>
        <h3 className="pf-fp-title" id={`${formId}-title`}>
          {title}
        </h3>
        {error}
        <div className="pf-fsheet-body">{children}</div>
        <div className="pf-fsheet-foot">
          {readOnly ? (
            <Button onClick={onCancel}>{t("formSheet.close")}</Button>
          ) : (
            <>
              <Button onClick={close}>{t("formSheet.cancel")}</Button>
              <Button type="primary" htmlType="submit" form={formId} loading={saving}>
                {submitLabel}
              </Button>
            </>
          )}
        </div>
      </section>
    </Sheet>
  );
}
