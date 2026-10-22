import { theme } from "antd";
import type { ReactNode } from "react";

export interface EmptyStateProps {
  /** Что это за экран и почему пусто — статус словами */
  title: string;
  /** Что здесь появится (тексты SPEC-v3 §7) */
  text: string;
  /** Одно действие: кнопка или ссылка */
  action?: ReactNode;
  /** Уровень заголовка: на странице — h2 под h1, в боковом окне — h3 */
  level?: 2 | 3;
  /** Компактный вид для бокового окна */
  compact?: boolean;
}

/**
 * Пустое состояние: статус + что здесь будет + одно действие (SPEC-v3 §5.3). Без иллюстраций и эмодзи.
 * Минимальная версия PLT-12; PLT-13 доводит набор общих компонентов.
 */
export function EmptyState({ title, text, action, level = 2, compact = false }: EmptyStateProps) {
  const { token } = theme.useToken();
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        textAlign: "center",
        gap: 8,
        padding: compact ? "32px 16px" : "56px 24px",
      }}
    >
      <Heading style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
        {title}
      </Heading>
      <p
        style={{
          margin: 0,
          maxWidth: 480,
          color: token.colorTextSecondary,
          lineHeight: "22px",
        }}
      >
        {text}
      </p>
      {action ? <div style={{ marginTop: 8 }}>{action}</div> : null}
    </div>
  );
}
