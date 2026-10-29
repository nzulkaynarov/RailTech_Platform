import { Button } from "antd";
import { useEffect, type CSSProperties } from "react";

export interface ContextualSaveBarProps {
  /** Флаг наличия несохранённых изменений (бар виден только при true) */
  visible: boolean;
  /** Текст статуса, по умолчанию "Есть несохранённые изменения" */
  message?: string;
  /** Подпись кнопки сохранения, по умолчанию "Сохранить изменения" */
  saveLabel?: string;
  /** Подпись кнопки отмены, по умолчанию "Отменить" */
  discardLabel?: string;
  /** Колбэк сохранения */
  onSave: () => void;
  /** Колбэк отмены / сброса */
  onDiscard: () => void;
  /** Флаг загрузки сохранения */
  loading?: boolean;
  /** Отключить кнопки */
  disabled?: boolean;
  /** Дополнительные CSS стили */
  style?: CSSProperties;
}

/**
 * Контекстный бар сохранения (Shopify Polaris pattern):
 * Прилипает к верху рабочей области (position: sticky, top: 0, z-index: 100),
 * высота 48px, контрастный тёмный фон #0f172a, белый текст.
 * Показывается только при наличии несохранённых изменений (visible === true).
 * Поддерживает хоткей Cmd+S (macOS) / Ctrl+S (Win/Linux).
 */
export function ContextualSaveBar({
  visible,
  message = "Есть несохранённые изменения",
  saveLabel = "Сохранить изменения",
  discardLabel = "Отменить",
  onSave,
  onDiscard,
  loading = false,
  disabled = false,
  style,
}: ContextualSaveBarProps) {
  // Глобальный хоткей Cmd+S / Ctrl+S при открытом баре (работает в раскладках EN и RU)
  useEffect(() => {
    if (!visible) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        (event.metaKey || event.ctrlKey) &&
        (event.key.toLowerCase() === "s" || event.code === "KeyS")
      ) {
        event.preventDefault();
        if (!loading && !disabled) {
          onSave();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [visible, loading, disabled, onSave]);

  if (!visible) {
    return null;
  }

  return (
    <div
      role="region"
      aria-label="Панель сохранения"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 100,
        height: 48,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 16px",
        marginBottom: 12,
        borderRadius: 8,
        background: "#0f172a",
        color: "#ffffff",
        boxShadow: "0 4px 12px rgba(0, 0, 0, 0.15)",
        transition: "all 0.2s ease-in-out",
        flex: "0 0 48px",
        ...style,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span
          aria-hidden="true"
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: "#f59e0b",
            boxShadow: "0 0 0 3px rgba(245, 158, 11, 0.25)",
            flex: "0 0 auto",
          }}
        />
        <span
          style={{
            fontWeight: 500,
            fontSize: 14,
            color: "#f8fafc",
            letterSpacing: "-0.01em",
          }}
        >
          {message}
        </span>
        <kbd
          aria-hidden="true"
          style={{
            padding: "1px 6px",
            borderRadius: 4,
            background: "rgba(255, 255, 255, 0.1)",
            border: "1px solid rgba(255, 255, 255, 0.2)",
            color: "#94a3b8",
            fontSize: 11,
            fontFamily: "inherit",
            lineHeight: "16px",
          }}
        >
          ⌘S
        </kbd>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Button
          ghost
          onClick={onDiscard}
          disabled={loading || disabled}
          style={{
            color: "#e2e8f0",
            borderColor: "rgba(255, 255, 255, 0.3)",
          }}
        >
          {discardLabel}
        </Button>
        <Button
          type="primary"
          onClick={onSave}
          loading={loading}
          disabled={disabled}
          style={{
            background: "#1677ff",
            borderColor: "#1677ff",
            fontWeight: 500,
          }}
        >
          {saveLabel}
        </Button>
      </div>
    </div>
  );
}
