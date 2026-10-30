import { Button, theme } from "antd";
import { useEffect, useRef, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";

import { UnsavedGuard } from "./UnsavedGuard";

export interface ContextualSaveBarProps {
  /** Есть несохранённые изменения — бар виден только тогда (место под него зарезервировано всегда) */
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
  /** Вопрос «Выйти без сохранения?» при уходе с несохранёнными правками; по умолчанию — есть */
  guard?: boolean;
  /** Параметры адреса, смена которых — уход из формы (`UnsavedGuard.params`): `tab` «Компании», `role` ролей */
  guardParams?: readonly string[];
  /** Класс места бара (ширина и отступ в форме); место — прямой потомок формы, чтобы бар прилипал к низу */
  className?: string;
  style?: CSSProperties;
}

const BAR_ATTR = "data-save-bar";

/** Ближайший прокручиваемый предок: рабочая область `#main-content` или тело бокового окна. */
function scrollParent(node: HTMLElement): HTMLElement | null {
  for (let el = node.parentElement; el; el = el.parentElement) {
    const overflow = getComputedStyle(el).overflowY;
    if ((overflow === "auto" || overflow === "scroll") && el.scrollHeight > el.clientHeight)
      return el;
  }
  return null;
}

/** Видимая рамка поля: у Select и DatePicker фокус на внутреннем input, рамка — у обёртки. */
function fieldBox(target: HTMLElement): DOMRect {
  const box =
    target.closest<HTMLElement>(".ant-select, .ant-picker, .ant-input-affix-wrapper") ?? target;
  return box.getBoundingClientRect();
}

const FIELD_GAP = 16;

function isMac(): boolean {
  return typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
}

/**
 * Бар несохранённых изменений (docs/architecture/platform-frontend.md §5): стоит в конце формы вместо её кнопки
 * «Сохранить», прилипает к низу прокручиваемой области и лежит поверх контента; «Отменить» и «Сохранить …», ⌘S / Ctrl+S
 * (и в раскладке RU). Место под бар зарезервировано и без правок, поэтому первый символ ничего не сдвигает (UX-1b, S6).
 * Уход с несохранёнными правками спрашивает «Выйти без сохранения?» (`UnsavedGuard`, A1).
 *
 * Только для обратимого сохранения настроек и черновиков: действие с последствиями для других (создать заявку,
 * отправить, подписать) остаётся главной кнопкой формы с блоком «Что произойдёт» (CONVENTIONS §2 п. 8). Если на экране
 * несколько баров, ⌘S сохраняет форму, в которой фокус. Статус объявляет скринридеру живой регион, который есть на
 * странице всегда, а не только при видимом баре.
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
  guard = true,
  guardParams,
  className,
  style,
}: ContextualSaveBarProps) {
  const { t } = useTranslation("ui");
  const { token } = theme.useToken();
  const rootRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  // «Отменить» может сам увести с формы (новая роль закрывается): этот переход вопроса не вызывает.
  const discarding = useRef(false);
  const discard = () => {
    discarding.current = true;
    try {
      onDiscard();
    } finally {
      window.setTimeout(() => {
        discarding.current = false;
      }, 0);
    }
  };
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

  // Поле в фокусе никогда не уходит под бар (UX-1b): у полей формы `scroll-margin-bottom` = место бара (переменная
  // `--pf-save-bar-space` у формы), а если поле всё же под баром — после фокуса, ввода или появления бара — область
  // прокручивается ровно настолько, чтобы поле стояло над баром с зазором 16 px.
  useEffect(() => {
    const scope = rootRef.current?.parentElement;
    const bar = barRef.current;
    const dock = rootRef.current;
    if (!scope || !bar || !dock) return;
    const space = () => {
      const offset = Number.parseFloat(getComputedStyle(dock).bottom) || 0;
      scope.style.setProperty(
        "--pf-save-bar-space",
        `${String(bar.offsetHeight + offset + FIELD_GAP)}px`,
      );
    };
    space();
    if (!visible) return;
    let frame = 0;
    const reveal = (target: Element | null) => {
      if (!(target instanceof HTMLElement) || bar.contains(target) || !scope.contains(target))
        return;
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const field = fieldBox(target);
        const barTop = bar.getBoundingClientRect().top;
        const overlap = field.bottom + FIELD_GAP - barTop;
        if (overlap <= 0) return;
        scrollParent(dock)?.scrollBy({ top: overlap });
      });
    };
    const onFocus = (event: FocusEvent) => {
      reveal(event.target as Element | null);
    };
    const onInput = (event: Event) => {
      reveal(event.target as Element | null);
    };
    scope.addEventListener("focusin", onFocus);
    scope.addEventListener("input", onInput);
    reveal(document.activeElement);
    return () => {
      window.cancelAnimationFrame(frame);
      scope.removeEventListener("focusin", onFocus);
      scope.removeEventListener("input", onInput);
    };
  }, [visible]);

  const colors = {
    "--pf-save-bar-bg": token.colorBgElevated,
    "--pf-save-bar-border": token.colorBorderSecondary,
    "--pf-save-bar-text": token.colorText,
    "--pf-save-bar-muted": token.colorTextSecondary,
    "--pf-save-bar-kbd-border": token.colorBorder,
    "--pf-save-bar-dot": token.colorWarning,
    "--pf-save-bar-shadow": token.boxShadowSecondary,
  } as CSSProperties;

  return (
    <div
      ref={rootRef}
      className={className ? `pf-save-dock ${className}` : "pf-save-dock"}
      style={colors}
    >
      <span role="status" className="pf-sr-only">
        {visible ? text : ""}
      </span>
      <UnsavedGuard
        when={visible && guard}
        busy={loading}
        params={guardParams}
        skipRef={discarding}
      />
      <div
        ref={barRef}
        {...(visible ? { [BAR_ATTR]: "" } : {})}
        className="pf-save-bar"
        role="region"
        aria-label={t("saveBar.label")}
        aria-hidden={visible ? undefined : true}
        // Без правок бар невидим, но держит место: форма не прыгает на первом символе.
        {...(visible ? {} : { inert: "" })}
        style={{ ...style, visibility: visible ? undefined : "hidden" }}
      >
        <div className="pf-save-bar-status" aria-hidden="true">
          <span className="pf-save-bar-dot" />
          <span>{text}</span>
          <kbd className="pf-save-bar-kbd">{isMac() ? "⌘S" : "Ctrl+S"}</kbd>
        </div>
        <div className="pf-save-bar-actions">
          <Button onClick={discard} disabled={loading}>
            {discardLabel ?? t("saveBar.discard")}
          </Button>
          <Button type="primary" onClick={onSave} loading={loading} disabled={disabled}>
            {saveLabel ?? t("saveBar.save")}
          </Button>
        </div>
      </div>
    </div>
  );
}
