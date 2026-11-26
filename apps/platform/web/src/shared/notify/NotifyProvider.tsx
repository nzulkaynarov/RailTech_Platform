import { App, Button } from "antd";
import { createContext, useContext, useMemo, type ReactNode } from "react";

/** Всплывающее уведомление слоя: ключ дедуплицирует, `duration: 0` — остаётся, пока его не закроют. */
export interface PushOptions {
  key: string;
  title: string;
  text?: string | undefined;
  /** Секунды до автозакрытия; 0 — не закрывать само («требует вашего действия») */
  duration: number;
  /** Одна кнопка действия: открыть объект */
  action?: { label: string; onClick: () => void } | undefined;
  onClose?: (() => void) | undefined;
}

export interface Notify {
  success: (text: string) => void;
  info: (text: string) => void;
  warning: (text: string) => void;
  error: (text: string) => void;
  push: (options: PushOptions) => void;
  close: (key: string) => void;
}

const NotifyContext = createContext<Notify | null>(null);

/**
 * Единый слой уведомлений Платформы (УВЕД-1): короткие подтверждения («Сохранено») и всплывающие уведомления о событиях идут
 * только отсюда. `antd` `message` и `notification` вне `src/shared/notify` не используются (ui-guards/notify-layer.test.ts).
 * Стек — не больше трёх, сверху справа (настройка `App` в providers.tsx).
 */
export function NotifyProvider({ children }: { children: ReactNode }) {
  const { message, notification } = App.useApp();
  const value = useMemo<Notify>(
    () => ({
      success: (text) => void message.success(text),
      info: (text) => void message.info(text),
      warning: (text) => void message.warning(text),
      error: (text) => void message.error(text),
      push: ({ key, title, text, duration, action, onClose }) => {
        notification.open({
          key,
          message: title,
          description: text,
          duration,
          placement: "topRight",
          showProgress: duration > 0,
          pauseOnHover: true,
          ...(action
            ? {
                actions: (
                  <Button
                    type="primary"
                    size="small"
                    onClick={() => {
                      action.onClick();
                      notification.destroy(key);
                    }}
                  >
                    {action.label}
                  </Button>
                ),
              }
            : {}),
          ...(onClose ? { onClose } : {}),
        });
      },
      close: (key) => {
        notification.destroy(key);
      },
    }),
    [message, notification],
  );
  return <NotifyContext.Provider value={value}>{children}</NotifyContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- хук рядом со своим провайдером
export function useNotify(): Notify {
  const value = useContext(NotifyContext);
  if (!value) throw new Error("Уведомления недоступны вне оболочки приложения");
  return value;
}
