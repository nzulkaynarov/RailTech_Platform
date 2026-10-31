import { Alert, App, Button, Input, InputNumber, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ListMailLogStatus,
  MailLogItem,
  MailLogItemStatus,
  SmtpConnector,
} from "../../../shared/api/generated/model";
import {
  useCheckSmtp,
  useGetSmtpConnector,
  useListMailLog,
  useSaveSmtpConnector,
  useSendSmtpTest,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { StatusTag } from "../../../shared/ui/StatusTag";
import {
  ActionForm,
  ActionToggle,
  ErrorNote,
  Field,
  Masked,
  PanelState,
  PanelTitle,
} from "./parts";
import { useRefreshIntegrations } from "./refresh";

const MAIL_STATUSES: readonly MailLogItemStatus[] = ["queued", "sent", "failed", "skipped_no_smtp"];
const SECURITY = ["starttls", "ssl", "none"] as const;
/** Сколько ждать итога «Проверить отправку»: опрос журнала раз в 2 с, не дольше минуты. */
const TEST_POLL_MS = 2000;
const TEST_WAIT_MS = 60_000;

/** Код причины из журнала (`rejected: SMTP 550`) → словами; неизвестный код — как есть. */
function useReason() {
  const { t, i18n } = useTranslation("integrations");
  return (error: string) => {
    const [code = "", ...rest] = error.split(":");
    const key = `mail.reason.${code.trim()}`;
    if (!i18n.exists(key, { ns: "integrations" })) return error;
    const detail = rest.join(":").trim();
    return detail ? `${t(key)} (${detail})` : t(key);
  };
}

/** Назначение письма: код шаблона системы-источника → словами; неизвестный — код. */
function usePurpose() {
  const { t, i18n } = useTranslation("integrations");
  return (row: MailLogItem) => {
    const code = row.purpose ?? row.template;
    const key = `mail.purpose.${code}`;
    return i18n.exists(key, { ns: "integrations" }) ? t(key) : code;
  };
}

function SettingsForm({ smtp, onDone }: { smtp: SmtpConnector; onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
  const refresh = useRefreshIntegrations();
  const [host, setHost] = useState(smtp.host);
  const [port, setPort] = useState<number | null>(smtp.port);
  const [security, setSecurity] = useState<(typeof SECURITY)[number]>(smtp.security);
  const [fromEmail, setFromEmail] = useState(smtp.from_email);
  const [fromName, setFromName] = useState(smtp.from_name);
  const [username, setUsername] = useState(smtp.username);
  const [smtpPassword, setSmtpPassword] = useState("");
  const save = useSaveSmtpConnector({
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t("mail.settings.saved"));
        onDone();
      },
    },
  });
  return (
    <ActionForm
      id="smtp"
      title={t("mail.settings.title")}
      submitLabel={t("mail.settings.submit")}
      pending={save.isPending}
      error={save.error}
      invalid={host.trim() === "" || port === null}
      consequence={[t("mail.settings.step1"), t("mail.settings.step2"), t("mail.settings.step3")]}
      onCancel={onDone}
      onSubmit={(password) => {
        save.mutate({
          data: {
            host: host.trim(),
            port: port ?? 587,
            security,
            from_email: fromEmail.trim(),
            from_name: fromName.trim(),
            username: username.trim() === "" ? null : username.trim(),
            smtp_password: smtpPassword === "" ? null : smtpPassword,
            password,
          },
        });
      }}
    >
      <Field id="smtp-host" label={t("mail.settings.host")}>
        <Input
          id="smtp-host"
          value={host}
          autoComplete="off"
          onChange={(event) => {
            setHost(event.target.value);
          }}
        />
      </Field>
      <div className="pf-int-row">
        <Field id="smtp-port" label={t("mail.settings.port")}>
          <InputNumber
            id="smtp-port"
            min={1}
            max={65535}
            value={port}
            onChange={(value) => {
              setPort(value);
            }}
          />
        </Field>
        <Field id="smtp-security" label={t("mail.settings.security")}>
          <Select
            id="smtp-security"
            value={security}
            style={{ minWidth: 160 }}
            options={SECURITY.map((value) => ({
              value,
              label: t(`mail.settings.securityValue.${value}`),
            }))}
            onChange={setSecurity}
          />
        </Field>
      </div>
      <Field id="smtp-from-email" label={t("mail.settings.fromEmail")}>
        <Input
          id="smtp-from-email"
          value={fromEmail}
          inputMode="email"
          autoComplete="off"
          onChange={(event) => {
            setFromEmail(event.target.value);
          }}
        />
      </Field>
      <Field id="smtp-from-name" label={t("mail.settings.fromName")}>
        <Input
          id="smtp-from-name"
          value={fromName}
          autoComplete="off"
          onChange={(event) => {
            setFromName(event.target.value);
          }}
        />
      </Field>
      <Field id="smtp-username" label={t("mail.settings.username")}>
        <Input
          id="smtp-username"
          value={username}
          autoComplete="off"
          onChange={(event) => {
            setUsername(event.target.value);
          }}
        />
      </Field>
      <Field
        id="smtp-password-value"
        label={t("mail.settings.smtpPassword")}
        hint={t("mail.settings.smtpPasswordHint")}
      >
        <Input
          id="smtp-password-value"
          type="password"
          autoComplete="off"
          value={smtpPassword}
          onChange={(event) => {
            setSmtpPassword(event.target.value);
          }}
        />
      </Field>
    </ActionForm>
  );
}

function MailLog() {
  const { t } = useTranslation("integrations");
  const { date } = useFormat();
  const reason = useReason();
  const purpose = usePurpose();
  const [status, setStatus] = useState<ListMailLogStatus | "all">("all");
  const log = useListMailLog({ limit: 20, ...(status === "all" ? {} : { status }) });
  return (
    <section className="pf-int-block" aria-labelledby="mail-log-title">
      <h4 id="mail-log-title">{t("mail.log.title")}</h4>
      <Field id="mail-log-status" label={t("mail.log.filter")}>
        <Select
          id="mail-log-status"
          value={status}
          style={{ maxWidth: 240 }}
          options={[
            { value: "all", label: t("mail.log.all") },
            ...MAIL_STATUSES.map((value) => ({ value, label: t(`mail.log.status.${value}`) })),
          ]}
          onChange={setStatus}
        />
      </Field>
      <PanelState query={log}>
        {(data) =>
          data.items.length === 0 ? (
            <p className="pf-hint" style={{ margin: 0 }}>
              {t("mail.log.empty")}
            </p>
          ) : (
            <ul className="pf-int-list" aria-label={t("mail.log.title")}>
              {data.items.map((row) => (
                <li key={row.id}>
                  <div className="pf-int-item-head">
                    <span className="pf-int-item-title">{row.subject}</span>
                    <StatusTag kind="mail" status={row.status}>
                      {t(`mail.log.status.${row.status}`)}
                    </StatusTag>
                  </div>
                  <p className="pf-int-sub">
                    {t(`mail.log.source.${row.source}`)} · {purpose(row)}
                    {row.attachments > 0
                      ? ` · ${t("mail.log.attachments", { count: row.attachments })}`
                      : ""}
                  </p>
                  <p className="pf-int-sub">
                    {row.to_email} · {date(row.sent_at ?? row.created_at, "datetime")}
                  </p>
                  {row.error ? (
                    <p className="pf-int-sub">
                      {t("mail.log.error", { error: reason(row.error) })}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )
        }
      </PanelState>
    </section>
  );
}

/** Итог «Проверить отправку» словами: строка журнала тестового письма, пока она в очереди — опрос. */
function TestResult({ id, email }: { id: number; email: string }) {
  const { t } = useTranslation("integrations");
  const reason = useReason();
  const [startedAt] = useState(() => Date.now());
  const log = useListMailLog(
    { limit: 20 },
    {
      query: {
        refetchInterval: (query) => {
          const row = query.state.data?.items.find((item) => item.id === id);
          const waiting = !row || row.status === "queued";
          return waiting && Date.now() - startedAt < TEST_WAIT_MS ? TEST_POLL_MS : false;
        },
      },
    },
  );
  const row = log.data?.items.find((item) => item.id === id);
  if (!row || row.status === "queued") {
    const late = log.dataUpdatedAt - startedAt >= TEST_WAIT_MS;
    return (
      <Alert
        type="info"
        showIcon
        role="status"
        message={t(late ? "mail.test.late" : "mail.test.waiting", { email })}
        description={row?.error ? t("mail.log.error", { error: reason(row.error) }) : undefined}
      />
    );
  }
  if (row.status === "sent") {
    return <Alert type="success" showIcon role="status" message={t("mail.test.sent", { email })} />;
  }
  return (
    <Alert
      type="error"
      showIcon
      role="status"
      message={t("mail.test.failed", { email })}
      description={row.error ? t("mail.log.error", { error: reason(row.error) }) : undefined}
    />
  );
}

function MailBody({ smtp, editable }: { smtp: SmtpConnector; editable: boolean }) {
  const { t } = useTranslation("integrations");
  const refresh = useRefreshIntegrations();
  const [open, setOpen] = useState(false);
  const check = useCheckSmtp({
    mutation: {
      onSuccess: () => {
        refresh();
      },
    },
  });
  const test = useSendSmtpTest({
    mutation: {
      onSuccess: () => {
        refresh();
      },
    },
  });
  return (
    <div className="pf-panel-stack">
      <DefinitionList
        items={[
          {
            label: t("mail.state"),
            value: smtp.configured ? t("mail.stateValue.configured") : t("mail.stateValue.none"),
          },
          {
            label: t("mail.server"),
            value: smtp.host ? `${smtp.host}:${String(smtp.port)}` : null,
          },
          {
            label: t("mail.settings.security"),
            value: smtp.host ? t(`mail.settings.securityValue.${smtp.security}`) : null,
          },
          { label: t("mail.settings.fromEmail"), value: smtp.from_email },
          { label: t("mail.settings.fromName"), value: smtp.from_name },
          { label: t("mail.settings.username"), value: smtp.username },
          {
            label: t("mail.settings.smtpPassword"),
            value: <Masked configured={smtp.password_configured} last4={smtp.password_last4} />,
          },
        ]}
      />
      {!smtp.secrets_enabled ? (
        <Alert type="warning" showIcon message={t("common.secretsOff")} />
      ) : null}
      {editable ? (
        <>
          <div className="pf-int-row">
            <Button
              loading={check.isPending}
              disabled={!smtp.configured}
              onClick={() => {
                check.mutate();
              }}
            >
              {t("mail.check.button")}
            </Button>
            <Button
              loading={test.isPending}
              disabled={!smtp.configured}
              onClick={() => {
                test.mutate();
              }}
            >
              {t("mail.test.button")}
            </Button>
          </div>
          {check.data ? (
            <Alert
              type={check.data.authenticated ? "success" : "warning"}
              showIcon
              role="status"
              message={t(check.data.authenticated ? "mail.check.ok" : "mail.check.noAuth")}
              description={t("mail.check.details", {
                server: check.data.server,
                ms: check.data.latency_ms,
              })}
            />
          ) : null}
          {test.data ? (
            <TestResult
              key={test.data.email_log_id}
              id={test.data.email_log_id}
              email={test.data.to_email}
            />
          ) : null}
          <ErrorNote error={check.error} />
          <ErrorNote error={test.error} />
          <ActionToggle label={t("mail.settings.button")} open={open} onToggle={setOpen}>
            <SettingsForm
              smtp={smtp}
              onDone={() => {
                setOpen(false);
              }}
            />
          </ActionToggle>
        </>
      ) : (
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("common.readOnly")}
        </p>
      )}
      <MailLog />
    </div>
  );
}

/** Карточка «Почта» — один отправитель ансамбля (W18A-P1): SMTP (настройки, пароль — маска), «Проверить связь»,
 * «Проверить отправку» с итогом словами, журнал доставки писем CRM, ERP и EDS. */
export function MailPanel({ editable }: { editable: boolean }) {
  const { t } = useTranslation("integrations");
  const query = useGetSmtpConnector();
  return (
    <div className="pf-panel-stack">
      <PanelTitle>{t("cards.mail.title")}</PanelTitle>
      <PanelState query={query}>
        {(smtp) => <MailBody smtp={smtp} editable={editable} />}
      </PanelState>
    </div>
  );
}
