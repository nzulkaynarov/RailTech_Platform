import { Button } from "antd";
import { useEffect, useRef, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";

export interface ContextualSaveBarProps {
  /** Есть несохранённые изменения — бар виден только тогда */
  visible: boolean;
  /** Текст статуса; по умолчанию `ui:saveBar.message` */
  message?: string;
  /** Подпись кнопки сохранения; по умолчанию `ui:saveBar.save` */
  saveLabel?: string;
  /** Подпись кнопки отмены; по умолчанию `ui:saveBar.discard` */
  discardLabel?: string;
  onSave: () => void;
  onDiscard: () => void;
  loading?: boolean;
  /** Сохранить нельзя (например, поле заполнено с ошибкой): изменения видны, кнопка и ⌘S не действуют */
  disabled?: boolean;
  style?: CSSProperties;
}

const BAR_ATTR = "data-save-bar";

function isMac(): boolean {
  return typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
}

/**
 * Бар несохранённых изменений (docs/architecture/platform-frontend.md §5): прилипает к верху формы, «Отменить» и
 * «Сохранить изменения», ⌘S / Ctrl+S (и в раскладке RU). Только для обратимого сохранения настроек и черновиков:
 * действие с последствиями для других (создать заявку, отправить, подписать) остаётся главной кнопкой формы с блоком
 * «Что произойдёт» (CONVENTIONS §2 п. 8). Если на экране несколько баров, ⌘S сохраняет форму, в которой фокус.
 * Статус объявляет скринридеру живой регион, который есть на странице всегда, а не только при видимом баре.
 */
export function ContextualSaveBar({
  visible,
  message,
  saveLabel,
  discardLabel,
  onSave,
  onDiscard,
  loading = false,
  disabled = false,
  style,
}: ContextualSaveBarProps) {
  const { t } = useTranslation("ui");
  const rootRef = useRef<HTMLDivElement>(null);
  const text = message ?? t("saveBar.message");

  useEffect(() => {
    if (!visible) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
      if (event.key.toLowerCase() !== "s" && event.code !== "KeyS") return;
      // Пока на экране есть несохранённое, ⌘S не открывает «Сохранить страницу» браузера.
      event.preventDefault();
      const container = rootRef.current?.parentElement;
      const bars = document.querySelectorAll(`[${BAR_ATTR}]`).length;
      const focusInside = container?.contains(document.activeElement) ?? false;
      if ((focusInside || bars === 1) && !loading && !disabled) onSave();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [visible, loading, disabled, onSave]);

  return (
    <>
      <span role="status" className="pf-sr-only">
        {visible ? text : ""}
      </span>
      {visible ? (
        <div
          ref={rootRef}
          {...{ [BAR_ATTR]: "" }}
          className="pf-save-bar"
          role="region"
          aria-label={t("saveBar.label")}
          style={style}
        >
          <div className="pf-save-bar-status" aria-hidden="true">
            <span className="pf-save-bar-dot" />
            <span>{text}</span>
            <kbd className="pf-save-bar-kbd">{isMac() ? "⌘S" : "Ctrl+S"}</kbd>
          </div>
          <div className="pf-save-bar-actions">
            <Button ghost onClick={onDiscard} disabled={loading}>
              {discardLabel ?? t("saveBar.discard")}
            </Button>
            <Button type="primary" onClick={onSave} loading={loading} disabled={disabled}>
              {saveLabel ?? t("saveBar.save")}
            </Button>
          </div>
        </div>
      ) : null}
    </>
  );
}
