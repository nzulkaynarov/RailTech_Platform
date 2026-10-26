import { Alert, Button, Skeleton } from "antd";
import { type ReactNode, useId } from "react";

import { ApiError } from "../api/errors";
import { EmptyState } from "./EmptyState";

import "./form-parts.css";

/** Поле формы с видимой подписью (`label for`) и подсказкой под ним. */
export function FormField({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="pf-fp-field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint ? (
        <span className="pf-hint" id={`${id}-hint`}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

/** Ошибка операции словами (`role="alert"`); текст готовит экран из кода и подкода ошибки. */
export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return <Alert type="error" showIcon role="alert" message={message} />;
}

/** Таблица, прокручиваемая по горизонтали на узком экране: область доступна с клавиатуры (WCAG 2.1.1). */
export function ScrollRegion({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="pf-fp-scroll" role="region" tabIndex={0} aria-label={label}>
      {children}
    </div>
  );
}

/** Кнопка, раскрывающая форму под собой: вторичные действия не превращают панель в стену полей. */
export function ActionToggle({
  label,
  open,
  onToggle,
  danger = false,
  disabled = false,
  children,
}: {
  label: string;
  open: boolean;
  onToggle: (open: boolean) => void;
  danger?: boolean;
  disabled?: boolean;
  children: ReactNode;
}) {
  const regionId = useId();
  return (
    <div className="pf-fp-form">
      <div className="pf-fp-row">
        <Button
          danger={danger}
          disabled={disabled}
          aria-expanded={open}
          aria-controls={open ? regionId : undefined}
          onClick={() => {
            onToggle(!open);
          }}
        >
          {label}
        </Button>
      </div>
      {open ? <div id={regionId}>{children}</div> : null}
    </div>
  );
}

export interface QueryLike<T> {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => unknown;
}

export interface QueryStateLabels {
  retry: string;
  loadError: { title: string; text: string };
  unavailable: { title: string; text: string };
  forbidden: { title: string; text: string };
}

/** Загрузка, «нет права» и сбой словами; данные получает функция-потомок. `level` — заголовок пустого состояния. */
export function QueryState<T>({
  query,
  labels,
  level = 2,
  compact = false,
  children,
}: {
  query: QueryLike<T>;
  labels: QueryStateLabels;
  level?: 2 | 3;
  compact?: boolean;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <Skeleton active paragraph={{ rows: 4 }} title={false} />;
  if (query.isError || query.data === undefined) {
    const error = query.error;
    const text =
      error instanceof ApiError && error.status === 403
        ? labels.forbidden
        : error instanceof ApiError && error.status >= 500
          ? labels.unavailable
          : labels.loadError;
    return (
      <EmptyState
        level={level}
        compact={compact}
        title={text.title}
        text={text.text}
        action={
          error instanceof ApiError && error.status === 403 ? undefined : (
            <Button
              onClick={() => {
                void query.refetch();
              }}
            >
              {labels.retry}
            </Button>
          )
        }
      />
    );
  }
  return <>{children(query.data)}</>;
}
