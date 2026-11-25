import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Card, Input, Select, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { TelegramGroup } from "../../../shared/api/generated/model";
import {
  getGetCrmClientTelegramGroupQueryKey,
  getListCrmTelegramGroupsQueryKey,
  useBindCrmTelegramGroup,
  useListCrmClients,
  useListCrmTelegramGroups,
  useUnbindCrmTelegramGroup,
} from "../../../shared/api/generated/platform-bff";
import { useDebounced } from "../../../shared/lib/useDebounced";
import { useFormat } from "../../../shared/lib/useFormat";
import { Dialog } from "../../../shared/ui/Dialog";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { GroupState } from "../../crm/clients/GroupState";

import "./telegram-groups.css";

/** Ошибка привязки словами: неверный код (404) и просроченный или уже использованный (409) различаются. */
function bindError(t: (key: string) => string, error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return t("tgGroups.errors.wrongCode");
    if (error.status === 409) {
      const reason = error.details["reason"];
      if (reason === "group_already_bound") return t("tgGroups.errors.alreadyBound");
      if (reason === "group_is_team_channel") return t("tgGroups.errors.teamChannel");
      return t("tgGroups.errors.expired");
    }
    if (error.status === 403) return t("tgGroups.errors.forbidden");
  }
  return t("tgGroups.errors.generic");
}

function ConnectForm() {
  const { t } = useTranslation("clients");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [clientId, setClientId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const clients = useListCrmClients(q ? { q } : undefined);
  const bind = useBindCrmTelegramGroup({
    mutation: {
      onSuccess: (group) => {
        void queryClient.invalidateQueries({ queryKey: getListCrmTelegramGroupsQueryKey() });
        if (group.client_id !== null) {
          void queryClient.invalidateQueries({
            queryKey: getGetCrmClientTelegramGroupQueryKey(group.client_id),
          });
        }
        setCode("");
        setClientId(null);
        setSearch("");
        void message.success(t("tgGroups.connected"));
      },
    },
  });
  const ready = code.trim().length >= 4 && clientId !== null;
  return (
    <Card>
      <h2 className="pf-bot-part-title">{t("tgGroups.connectTitle")}</h2>
      <ol className="pf-tgg-steps">
        {(["add", "code", "enter"] as const).map((step) => (
          <li key={step}>{t(`tgGroups.steps.${step}`)}</li>
        ))}
      </ol>
      <form
        className="pf-tgg-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) bind.mutate({ data: { code: code.trim(), client_id: clientId } });
        }}
      >
        <FormField id="tgg-code" label={t("tgGroups.code")}>
          <Input
            id="tgg-code"
            value={code}
            maxLength={16}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => {
              setCode(event.target.value.toUpperCase());
            }}
          />
        </FormField>
        <FormField id="tgg-client" label={t("tgGroups.client")}>
          <Select
            id="tgg-client"
            showSearch
            filterOption={false}
            value={clientId}
            placeholder={t("tgGroups.clientPlaceholder")}
            notFoundContent={t("tgGroups.noClients")}
            loading={clients.isFetching}
            options={(clients.data?.items ?? []).map((c) => ({
              value: c.id,
              label: c.inn ? `${c.name} · ${c.inn}` : c.name,
            }))}
            onSearch={setSearch}
            onChange={(value: number) => {
              setClientId(value);
            }}
          />
        </FormField>
        <Button type="primary" htmlType="submit" disabled={!ready} loading={bind.isPending}>
          {t("tgGroups.connect")}
        </Button>
      </form>
      {bind.isError ? <ErrorNote message={bindError(t, bind.error)} /> : null}
    </Card>
  );
}

function GroupRow({ group, editable }: { group: TelegramGroup; editable: boolean }) {
  const { t } = useTranslation("clients");
  const fmt = useFormat();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const unbind = useUnbindCrmTelegramGroup({
    mutation: {
      onSuccess: () => {
        setConfirming(false);
        void queryClient.invalidateQueries({ queryKey: getListCrmTelegramGroupsQueryKey() });
        if (group.client_id !== null) {
          void queryClient.invalidateQueries({
            queryKey: getGetCrmClientTelegramGroupQueryKey(group.client_id),
          });
        }
        void message.success(t("tgGroups.disconnected"));
      },
    },
  });
  const bound = group.state === "connected" || group.state === "needs_admin";
  return (
    <li className="pf-tgg-row">
      <div className="pf-tgg-main">
        <strong>{group.title}</strong>
        <span className={group.client_name ? undefined : "pf-hint"}>
          {group.client_name ?? t("tgGroups.pickClient")}
        </span>
        {group.bound_at ? (
          <span className="pf-hint">{t("tgGroups.since", { date: fmt.date(group.bound_at) })}</span>
        ) : null}
        {group.state === "code_expired" ? (
          <span className="pf-hint">{t("tgGroups.expiredHint")}</span>
        ) : null}
        {group.state === "needs_admin" ? (
          <span className="pf-hint">{t("tgGroups.needsAdminHint")}</span>
        ) : null}
      </div>
      <GroupState state={group.state} />
      {editable && bound ? (
        <Button
          onClick={() => {
            setConfirming(true);
          }}
          aria-label={t("tgGroups.disconnectLabel", { name: group.title })}
        >
          {t("tgGroups.disconnect")}
        </Button>
      ) : null}
      {confirming ? (
        <Dialog
          title={t("tgGroups.confirmTitle")}
          okLabel={t("tgGroups.disconnect")}
          danger
          loading={unbind.isPending}
          onOk={() => {
            unbind.mutate({ chatId: group.chat_id });
          }}
          onCancel={() => {
            setConfirming(false);
          }}
        >
          <p>{t("tgGroups.confirmText", { name: group.title })}</p>
          {unbind.isError ? <ErrorNote message={t("tgGroups.errors.generic")} /> : null}
        </Dialog>
      ) : null}
    </li>
  );
}

/**
 * Настройки · Telegram · «Группы с клиентами» (ТГ-1б, ADR-0032): группы, куда добавлен бот, привязка кодом из группы к
 * клиенту (три шага, одна главная кнопка) и отключение с подтверждением. Тема на заявку и правила группы — ТГ-2, ТГ-3:
 * переключателей без поведения здесь нет. Без права на клиентов — пояснение; с чтением — список без формы и кнопок.
 */
export function TelegramGroups() {
  const { t } = useTranslation("clients");
  const { me } = useAuth();
  const seesClients = canSee(me, { resource: "crm.clients" });
  // кнопки — как на странице Telegram: правка настроек (`admin: full`) и клиенты (`crm.clients: full`)
  const editable = canEdit(me, "crm.clients") && canEdit(me, "admin");
  const list = useListCrmTelegramGroups({ query: { enabled: seesClients } });
  if (!seesClients) {
    return (
      <Card>
        <EmptyState
          level={3}
          compact
          title={t("tgGroups.noAccess.title")}
          text={t("tgGroups.noAccess.text")}
        />
      </Card>
    );
  }
  return (
    <div className="pf-panel-stack">
      {editable ? <ConnectForm /> : null}
      <Card>
        <h2 className="pf-bot-part-title">{t("tgGroups.title")}</h2>
        {list.isPending ? (
          <Skeleton active paragraph={{ rows: 3 }} title={false} />
        ) : list.isError ? (
          <ErrorNote message={t("tgGroups.errors.load")} />
        ) : list.data.items.length ? (
          <ul className="pf-tgg-list">
            {list.data.items.map((group) => (
              <GroupRow key={group.chat_id} group={group} editable={editable} />
            ))}
          </ul>
        ) : (
          <EmptyState
            level={3}
            compact
            title={t("tgGroups.emptyTitle")}
            text={t("tgGroups.emptyText")}
          />
        )}
      </Card>
    </div>
  );
}
