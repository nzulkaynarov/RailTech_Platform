import { Alert, Button, Input, Skeleton } from "antd";
import { type FormEvent, type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { IntegrationStatus } from "../../../shared/api/generated/model";
import { Consequence } from "../../../shared/ui/Consequence";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { integrationErrorText, isForbidden, isWrongPassword } from "./errors";
import { LEVEL_TONE } from "./levels";

import "./integrations.css";

export function LevelTag({ level }: { level: IntegrationStatus }) {
  const { t } = useTranslation("integrations");
  return <StatusTag tone={LEVEL_TONE[level]}>{t(`status.${level}`)}</StatusTag>;
}

export function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="pf-int-field">
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

/** Ошибка операции словами (`role="alert"`): подкод CRM, затем код BFF; значений секретов в ней нет. */
export function ErrorNote({ error, id }: { error: unknown; id?: string }) {
  const { t } = useTranslation("integrations");
  if (!error) return null;
  return (
    <div id={id}>
      <Alert type="error" showIcon role="alert" message={integrationErrorText(t, error)} />
    </div>
  );
}

export interface ActionFormProps {
  /** Уникальная часть id полей */
  id: string;
  /** Подпись группы для скринридера */
  title: string;
  /** Блок «Что произойдёт» перед опасным действием */
  consequence?: readonly ReactNode[];
  submitLabel: string;
  danger?: boolean;
  /** Пароль администратора (повторный ввод) — по умолчанию да */
  needsPassword?: boolean;
  pending: boolean;
  error: unknown;
  onSubmit: (password: string) => void;
  onCancel?: () => void;
  /** Кнопка отправки недоступна (форма не заполнена) */
  invalid?: boolean;
  children?: ReactNode;
}

/**
 * Форма действия над подключением (SPEC-v3 §5.3, §7.6): поля, повторный ввод пароля администратора для секретов, блок «Что
 * произойдёт» и одна главная кнопка. Пароль живёт только в состоянии формы и уходит в BFF одним запросом; ошибка пароля
 * подсвечивает поле.
 */
export function ActionForm({
  id,
  title,
  consequence,
  submitLabel,
  danger = false,
  needsPassword = true,
  pending,
  error,
  onSubmit,
  onCancel,
  invalid = false,
  children,
}: ActionFormProps) {
  const { t } = useTranslation("integrations");
  const [password, setPassword] = useState("");
  const passwordId = `${id}-password`;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (pending || invalid || (needsPassword && password === "")) return;
    onSubmit(password);
  };
  return (
    <form className="pf-int-form" onSubmit={submit} aria-label={title} noValidate>
      {children}
      {needsPassword ? (
        <Field id={passwordId} label={t("common.password")} hint={t("common.passwordHint")}>
          <Input
            id={passwordId}
            type="password"
            autoComplete="off"
            value={password}
            status={isWrongPassword(error) ? "error" : undefined}
            aria-describedby={`${passwordId}-hint`}
            aria-invalid={isWrongPassword(error) || undefined}
            onChange={(event) => {
              setPassword(event.target.value);
            }}
          />
        </Field>
      ) : null}
      {consequence ? <Consequence items={consequence} /> : null}
      <ErrorNote error={error} id={`${id}-error`} />
      <div className="pf-int-row">
        <Button
          htmlType="submit"
          type="primary"
          danger={danger}
          loading={pending}
          disabled={invalid || (needsPassword && password === "")}
        >
          {submitLabel}
        </Button>
        {onCancel ? (
          <Button onClick={onCancel} disabled={pending}>
            {t("common.cancel")}
          </Button>
        ) : null}
      </div>
    </form>
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
    <div className="pf-int-form">
      <div className="pf-int-row">
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

interface QueryLike<T> {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => unknown;
}

/** Загрузка, «нет права в CRM» и сбой словами; данные получает функция-потомок. */
export function PanelState<T>({
  query,
  children,
}: {
  query: QueryLike<T>;
  children: (data: T) => ReactNode;
}) {
  const { t } = useTranslation("integrations");
  if (query.isPending) return <Skeleton active paragraph={{ rows: 4 }} title={false} />;
  if (query.isError || query.data === undefined) {
    if (isForbidden(query.error)) {
      return (
        <EmptyState
          level={3}
          compact
          title={t("panel.forbidden.title")}
          text={t("panel.forbidden.text")}
        />
      );
    }
    const down = query.error instanceof ApiError && query.error.status >= 500;
    return (
      <EmptyState
        level={3}
        compact
        title={t(down ? "panel.unavailable.title" : "panel.loadError.title")}
        text={t(down ? "panel.unavailable.text" : "panel.loadError.text")}
        action={
          <Button
            onClick={() => {
              void query.refetch();
            }}
          >
            {t("common.retry")}
          </Button>
        }
      />
    );
  }
  return <>{children(query.data)}</>;
}

export function PanelTitle({
  children,
  status,
}: {
  children: ReactNode;
  status?: IntegrationStatus;
}) {
  return (
    <div className="pf-int-item-head">
      <h3 className="pf-int-panel-title">{children}</h3>
      {status ? <LevelTag level={status} /> : null}
    </div>
  );
}

/** Таблица, которая прокручивается по горизонтали на узком экране: область доступна с клавиатуры (WCAG 2.1.1). */
export function ScrollTable({ label, children }: { label: string; children: ReactNode }) {
  const { t } = useTranslation("integrations");
  return (
    <div
      className="pf-int-table-wrap"
      role="region"
      tabIndex={0}
      aria-label={t("common.tableScroll", { name: label })}
    >
      {children}
    </div>
  );
}

/** Маска секрета: «задан» и последние четыре символа, сам секрет сюда не приходит никогда. */
export function Masked({ configured, last4 }: { configured: boolean; last4: string | null }) {
  const { t } = useTranslation("integrations");
  if (!configured) return <>{t("common.notSet")}</>;
  return (
    <>
      <span aria-hidden="true">{`•••• ${last4 ?? ""}`.trim()}</span>
      <span className="pf-sr-only">
        {last4 ? t("common.maskedLast4", { last4 }) : t("common.set")}
      </span>
    </>
  );
}
