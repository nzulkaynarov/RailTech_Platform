import { Alert, App, Button, Checkbox, Input, InputNumber, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ImapConnector } from "../../../shared/api/generated/model";
import {
  getGetImapConnectorQueryKey,
  useCheckImap,
  useGetImapConnector,
  useSaveImapConnector,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { choiceOf, foldersOf } from "./folderChoice";
import { InboundFolders } from "./InboundFolders";
import { InboundHistory } from "./InboundHistory";
import { ActionForm, ActionToggle, ErrorNote, Field, Masked, PanelState } from "./parts";
import { useRefreshIntegrations } from "./refresh";
import { useQueryClient } from "@tanstack/react-query";

const SECURITY = ["ssl", "starttls"] as const;

/** Код причины сбоя приёма → словами; неизвестный — как есть. */
function useImapReason() {
  const { t, i18n } = useTranslation("integrations");
  return (kind: string) => {
    const key = `mail.inbound.reason.${kind}`;
    return i18n.exists(key, { ns: "integrations" }) ? t(key) : kind;
  };
}

function InboundForm({ imap, onDone }: { imap: ImapConnector; onDone: () => void }) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
  const client = useQueryClient();
  const refresh = useRefreshIntegrations();
  const [host, setHost] = useState(imap.host);
  const [port, setPort] = useState<number | null>(imap.port);
  const [security, setSecurity] = useState<(typeof SECURITY)[number]>(imap.security);
  const [folders, setFolders] = useState(() => choiceOf(imap.folders, imap.mailbox));
  const [username, setUsername] = useState(imap.username);
  const [appPassword, setAppPassword] = useState("");
  const [assist, setAssist] = useState(imap.assist_enabled);
  const save = useSaveImapConnector({
    mutation: {
      onSuccess: (data) => {
        client.setQueryData(getGetImapConnectorQueryKey(), data);
        refresh();
        void message.success(t("mail.inbound.saved"));
        onDone();
      },
    },
  });
  return (
    <ActionForm
      id="imap"
      title={t("mail.inbound.settings")}
      submitLabel={t("mail.settings.submit")}
      pending={save.isPending}
      error={save.error}
      invalid={port === null || foldersOf(folders).every((f) => f.spam)}
      onCancel={onDone}
      onSubmit={(password) => {
        save.mutate({
          data: {
            host: host.trim(),
            port: port ?? 993,
            security,
            mailbox: folders.regular[0] ?? "INBOX",
            folders: foldersOf(folders),
            assist_enabled: assist,
            username: username.trim() === "" ? null : username.trim(),
            imap_password: appPassword === "" ? null : appPassword,
            password,
          },
        });
      }}
    >
      <Field id="imap-host" label={t("mail.inbound.host")} hint={t("mail.inbound.hostHint")}>
        <Input
          id="imap-host"
          value={host}
          autoComplete="off"
          onChange={(event) => {
            setHost(event.target.value);
          }}
        />
      </Field>
      <div className="pf-int-row">
        <Field id="imap-port" label={t("mail.settings.port")}>
          <InputNumber
            id="imap-port"
            min={1}
            max={65535}
            value={port}
            onChange={(value) => {
              setPort(value);
            }}
          />
        </Field>
        <Field id="imap-security" label={t("mail.settings.security")}>
          <Select
            id="imap-security"
            value={security}
            style={{ minWidth: 160 }}
            options={SECURITY.map((value) => ({
              value,
              label: t(`mail.inbound.securityValue.${value}`),
            }))}
            onChange={setSecurity}
          />
        </Field>
      </div>
      <InboundFolders
        known={imap.folders}
        value={folders}
        onChange={setFolders}
        canFind={imap.configured}
      />
      <Field id="imap-username" label={t("mail.inbound.username")}>
        <Input
          id="imap-username"
          value={username}
          inputMode="email"
          autoComplete="off"
          onChange={(event) => {
            setUsername(event.target.value);
          }}
        />
      </Field>
      <Field
        id="imap-password-value"
        label={t("mail.inbound.appPassword")}
        hint={t("mail.inbound.appPasswordHint")}
      >
        <Input
          id="imap-password-value"
          type="password"
          autoComplete="off"
          value={appPassword}
          onChange={(event) => {
            setAppPassword(event.target.value);
          }}
        />
      </Field>
      <Checkbox
        checked={assist}
        onChange={(event) => {
          setAssist(event.target.checked);
        }}
      >
        {t("mail.inbound.assist")}
      </Checkbox>
    </ActionForm>
  );
}

function InboundBody({ imap, editable }: { imap: ImapConnector; editable: boolean }) {
  const { t } = useTranslation("integrations");
  const { date } = useFormat();
  const reason = useImapReason();
  const [open, setOpen] = useState(false);
  const check = useCheckImap();
  const last = imap.last_error_kind
    ? t("mail.inbound.lastError", { reason: reason(imap.last_error_kind) })
    : imap.last_ok_at
      ? t("mail.inbound.lastOk", { at: date(imap.last_ok_at, "datetime") })
      : null;
  return (
    <div className="pf-panel-stack">
      <DefinitionList
        items={[
          {
            label: t("mail.state"),
            value: imap.configured ? t("mail.inbound.on") : t("mail.inbound.off"),
          },
          {
            label: t("mail.server"),
            value: imap.host ? `${imap.host}:${String(imap.port)}` : null,
          },
          {
            label: t("mail.inbound.folders"),
            value: imap.host
              ? imap.folders
                  .map((f) => (f.spam ? `${f.label} (${t("mail.inbound.spamMark")})` : f.label))
                  .join(", ") || imap.mailbox
              : null,
          },
          { label: t("mail.inbound.username"), value: imap.username || null },
          {
            label: t("mail.inbound.appPassword"),
            value: <Masked configured={imap.password_configured} last4={imap.password_last4} />,
          },
          {
            label: t("mail.inbound.assistLabel"),
            value: imap.assist_enabled ? t("mail.inbound.assistOn") : t("mail.inbound.assistOff"),
          },
          { label: t("mail.inbound.lastPoll"), value: last },
        ]}
      />
      {imap.last_error_kind ? (
        <Alert type="warning" showIcon message={reason(imap.last_error_kind)} />
      ) : null}
      {editable ? (
        <>
          <div className="pf-int-row">
            <Button
              loading={check.isPending}
              disabled={!imap.configured}
              onClick={() => {
                check.mutate();
              }}
            >
              {t("mail.inbound.check")}
            </Button>
          </div>
          {check.data ? (
            <Alert
              type={check.data.ok ? "success" : "error"}
              showIcon
              role="status"
              message={
                check.data.ok
                  ? t("mail.inbound.checkOk", { count: check.data.messages ?? 0 })
                  : reason(check.data.error_kind ?? "unavailable")
              }
            />
          ) : null}
          <ErrorNote error={check.error} />
          {imap.configured ? <InboundHistory history={imap.history} reason={reason} /> : null}
          <ActionToggle label={t("mail.inbound.button")} open={open} onToggle={setOpen}>
            <InboundForm
              imap={imap}
              onDone={() => {
                setOpen(false);
              }}
            />
          </ActionToggle>
        </>
      ) : null}
    </div>
  );
}

/** «Приём» в карточке «Почта» (W18A-P2): общий ящик IMAP, пароль приложения только на запись, «Проверить приём»,
 * выключатель помощника канцелярии, итог последнего опроса. */
export function InboundMailBlock({ editable }: { editable: boolean }) {
  const { t } = useTranslation("integrations");
  // Пока идёт загрузка писем за период — ход раз в 2 секунды (W18A-P2-2).
  const query = useGetImapConnector({
    query: {
      refetchInterval: (q) => (q.state.data?.history?.status === "running" ? 2000 : false),
    },
  });
  return (
    <section className="pf-int-block" aria-labelledby="imap-title">
      <h4 id="imap-title">{t("mail.inbound.title")}</h4>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("mail.inbound.intro")}
      </p>
      <PanelState query={query}>
        {(imap) => <InboundBody imap={imap} editable={editable} />}
      </PanelState>
    </section>
  );
}
