import { App, Button, Drawer } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Sheet } from "./Sheet";
import "./form-parts.css";

/**
 * Форма на 4–15 полей или карточка объекта — в боковой панели (стандарт интерфейса §6): заголовок сверху, поля в одну
 * колонку, подвал закреплён — «Отмена» и справа главная кнопка. Кнопка либо отправляет форму вызывающего (`formId`),
 * либо зовёт `onSubmit`. Изменённую форму (`dirty`) нельзя закрыть молча: «Отмена» спрашивает, выйти ли без сохранения.
 *
 * Пока форма открыта, каркас держит панель открытой (адрес и выбор пользователя не меняются), а карточка объекта,
 * уже открытая в панели, скрыта и возвращается после. На телефоне — лист на весь экран (`Sheet`). Форма из карточки,
 * открытой выезжающим окном, — `layer="drawer"`: своя панель поверх карточки с теми же шапкой и подвалом.
 */
/** Ширины выезжающей формы (стандарт интерфейса §6): 480 и 640 px, на узком экране — вся ширина. */
const FORM_DRAWER_WIDTH = 480;
const FORM_DRAWER_WIDE = 640;

export function FormSheet({
  title,
  formId,
  submitLabel,
  saving,
  error,
  dirty = false,
  readOnly = false,
  submitDisabled = false,
  layer = "panel",
  wide = false,
  onSubmit,
  onCancel,
  children,
}: {
  title: string;
  /** Id формы вызывающего: главная кнопка отправляет её. Нет — нужен `onSubmit` */
  formId?: string;
  submitLabel: string;
  saving: boolean;
  /** Ошибка без своего поля — над полями; ошибки полей стоят под полями */
  error?: ReactNode;
  /** В форме есть несохранённые изменения */
  dirty?: boolean;
  /** Просмотр без права на изменение: вместо «Отмена» и главной кнопки — «Закрыть» */
  readOnly?: boolean;
  submitDisabled?: boolean;
  /**
   * Где открыть форму: `panel` — боковое окно каркаса (форма о строке списка); `drawer` — выезжающая панель 480 px
   * поверх всего, для формы из карточки объекта, которая сама открыта выезжающим окном.
   */
  layer?: "panel" | "drawer";
  /** Широкая выезжающая панель 640 px: форма с таблицей строк или предпросмотром (только `layer="drawer"`) */
  wide?: boolean;
  onSubmit?: () => void;
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
  const titleId = `${formId ?? "pf-fsheet"}-title`;
  const buttons = readOnly ? (
    <Button onClick={onCancel}>{t("formSheet.close")}</Button>
  ) : (
    <>
      <Button onClick={close}>{t("formSheet.cancel")}</Button>
      <Button
        type="primary"
        loading={saving}
        disabled={submitDisabled}
        {...(formId ? { htmlType: "submit" as const, form: formId } : {})}
        {...(onSubmit ? { onClick: onSubmit } : {})}
      >
        {submitLabel}
      </Button>
    </>
  );
  if (layer === "drawer") {
    return (
      <Drawer
        open
        width={wide ? FORM_DRAWER_WIDE : FORM_DRAWER_WIDTH}
        title={title}
        onClose={close}
        destroyOnHidden
        maskClosable={!dirty}
        rootClassName="pf-fdrawer"
        footer={<div className="pf-fdrawer-foot">{buttons}</div>}
      >
        <div className="pf-fsheet-stack">
          {error}
          {children}
        </div>
      </Drawer>
    );
  }
  return (
    <Sheet label={title} onClose={close} over>
      <section className="pf-fsheet" aria-labelledby={titleId}>
        <h3 className="pf-fp-title" id={titleId}>
          {title}
        </h3>
        {error}
        <div className="pf-fsheet-body">{children}</div>
        <div className="pf-fsheet-foot">{buttons}</div>
      </section>
    </Sheet>
  );
}
