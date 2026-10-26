import { Alert, App, Button, Input, InputNumber, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ListMailLogStatus,
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
import { type StatusTone } from "../../../shared/lib/statuses";
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

const MAIL_TONE: Record<MailLogItemStatus, StatusTone> = {
  queued: "blue",
  sent: "green",
  failed: "red",
  skipped_no_smtp: "default",
};
const MAIL_STATUSES: readonly MailLogItemStatus[] = ["queued", "sent", "failed", "skipped_no_smtp"];
const SECURITY = ["starttls", "ssl", "none"] as const;

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
                    <StatusTag tone={MAIL_TONE[row.status]}>
                      {t(`mail.log.status.${row.status}`)}
                    </StatusTag>
                  </div>
                  <p className="pf-int-sub">
                    {row.to_email} · {date(row.sent_at ?? row.created_at, "datetime")}
                  </p>
                  {row.error ? (
                    <p className="pf-int-sub">{t("mail.log.error", { error: row.error })}</p>
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

function MailBody({ smtp, editable }: { smtp: SmtpConnector; editable: boolean }) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
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
      onSuccess: (queued) => {
        refresh();
        void message.success(t("mail.test.queued", { email: queued.to_email }));
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

/** Карточка «Почта»: SMTP (настройки, пароль — маска), «Проверить», тестовое письмо, журнал отправок. */
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
