import { App, Button } from "antd";
import { useEffect, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { useViewport } from "../../app/shell/useViewport";
import { Sheet } from "./Sheet";
import "./form-parts.css";

/**
 * Форма на 4–15 полей или карточка объекта — в боковой панели (стандарт интерфейса §6): заголовок сверху, поля в одну
 * колонку, подвал закреплён — «Отмена» и справа главная кнопка. Кнопка либо отправляет форму вызывающего (`formId`),
 * либо зовёт `onSubmit`. Изменённую форму (`dirty`) нельзя закрыть молча: «Отмена» спрашивает, выйти ли без сохранения.
 *
 * Панель открывается сама и закрывается вместе с формой, если до неё была закрыта; карточка объекта, уже открытая в
 * панели, на время формы скрыта и возвращается после. На телефоне — лист на весь экран (`Sheet`).
 */
export function FormSheet({
  title,
  formId,
  submitLabel,
  saving,
  error,
  dirty = false,
  readOnly = false,
  submitDisabled = false,
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
  onSubmit?: () => void;
  onCancel: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation("ui");
  const { modal } = App.useApp();
  const { mobile } = useViewport();
  const [, setParams] = useSearchParams();
  // Панель под форму: открыть, а при закрытии формы вернуть адрес как был (закрытая панель снова закрыта).
  useEffect(() => {
    if (mobile) return;
    let before: { panel: string | null; tab: string | null } | null = null;
    setParams(
      (prev) => {
        before = { panel: prev.get("panel"), tab: prev.get("tab") };
        if (before.panel === "open" && (before.tab ?? "card") === "card") return prev;
        const next = new URLSearchParams(prev);
        next.set("panel", "open");
        next.set("tab", "card");
        return next;
      },
      { replace: true },
    );
    return () => {
      setParams(
        (prev) => {
          if (!before || (before.panel === "open" && (before.tab ?? "card") === "card"))
            return prev;
          const next = new URLSearchParams(prev);
          if (before.panel === null) next.delete("panel");
          else next.set("panel", before.panel);
          if (before.tab === null) next.delete("tab");
          else next.set("tab", before.tab);
          return next;
        },
        { replace: true },
      );
    };
  }, [mobile, setParams]);

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
  return (
    <Sheet label={title} onClose={close} over>
      <section className="pf-fsheet" aria-labelledby={titleId}>
        <h3 className="pf-fp-title" id={titleId}>
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
          )}
        </div>
      </section>
    </Sheet>
  );
}
