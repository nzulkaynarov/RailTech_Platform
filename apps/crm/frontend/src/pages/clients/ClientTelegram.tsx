import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Flex, InputNumber, List, Select, Tag, Typography } from "antd";
import { useState } from "react";

import { adminKeys } from "../../api/adminQueries";
import { linkTelegram, unlinkTelegram } from "../../api/generated/crm";
import type { ClientDetail, IdentityOut } from "../../api/generated/model";
import { unwrap } from "../../api/http";
import { RowActions } from "../../components/RowActions";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useConfirmDanger } from "../../hooks/useConfirmDanger";
import { t } from "../../i18n/ru";
import { formatDate } from "../../lib/time";

type Action = { kind: "link" | "unlink"; tgUserId: number };

function identityLabel(i: IdentityOut): string {
  const name = i.tg_username ? `@${i.tg_username}` : (i.tg_first_name ?? "");
  return `${name} · ${String(i.tg_user_id)}`;
}

function useTelegramAction(clientId: number) {
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  return useMutation({
    mutationFn: async (a: Action) => {
      if (a.kind === "link")
        return unwrap(await linkTelegram(clientId, { tg_user_id: a.tgUserId }));
      return unwrap(await unlinkTelegram(clientId, a.tgUserId));
    },
    onSuccess: (_, a) => {
      void message.success(a.kind === "link" ? t.clients.linked : t.clients.unlinked);
      void client.invalidateQueries({ queryKey: adminKeys.client(clientId) });
    },
    onError: useApiErrorToast(),
  });
}

/** Ввод Telegram ID: на узком экране поле и кнопка переносятся, не выходят за край. */
function LinkById({ pending, onLink }: { pending: boolean; onLink: (id: number) => void }) {
  const [tgId, setTgId] = useState<number | null>(null);
  return (
    <Flex wrap gap="small" className="link-by-id">
      <InputNumber
        aria-label={t.clients.tgId}
        placeholder={t.clients.tgId}
        className="compact-input"
        min={1}
        value={tgId}
        onChange={setTgId}
      />
      <Button
        disabled={tgId === null}
        loading={pending}
        onClick={() => {
          if (tgId !== null) onLink(tgId);
          setTgId(null);
        }}
      >
        {t.clients.link}
      </Button>
    </Flex>
  );
}

type ListProps = { items: IdentityOut[]; onAction: (i: IdentityOut) => void };

function Identities({ items, canWrite, onAction }: ListProps & { canWrite: boolean }) {
  const menu = (i: IdentityOut) => (
    <RowActions
      key="menu"
      label={t.clients.accountActions.replace("{account}", identityLabel(i))}
      actions={[
        {
          key: "unlink",
          label: t.clients.unlink,
          danger: true,
          onClick: () => {
            onAction(i);
          },
        },
      ]}
    />
  );
  return (
    <List
      size="small"
      dataSource={items}
      locale={{
        emptyText: <Typography.Text type="secondary">{t.clients.telegramEmpty}</Typography.Text>,
      }}
      renderItem={(i) => (
        <List.Item actions={canWrite ? [menu(i)] : []}>
          <span>
            {identityLabel(i)}{" "}
            {i.verified_at ? (
              <Tag>{`${t.clients.verified} ${formatDate(i.verified_at)}`}</Tag>
            ) : null}
          </span>
        </List.Item>
      )}
    />
  );
}

/** Привязка: выбор аккаунта из лидов клиента; ввод ID — по ссылке «Ввести ID вручную». */
function LinkPicker({
  candidates,
  pending,
  onLink,
}: {
  candidates: IdentityOut[];
  pending: boolean;
  onLink: (id: number) => void;
}) {
  const [picked, setPicked] = useState<number | null>(null);
  const [manual, setManual] = useState(false);
  return (
    <Flex vertical gap="small">
      {candidates.length ? (
        <Flex wrap gap="small">
          <Select<number>
            aria-label={t.clients.pickFromLeads}
            placeholder={t.clients.pickFromLeads}
            className="filter-lg"
            value={picked}
            onChange={setPicked}
            options={candidates.map((i) => ({ value: i.tg_user_id, label: identityLabel(i) }))}
          />
          <Button
            disabled={picked === null}
            loading={pending}
            onClick={() => {
              if (picked !== null) onLink(picked);
              setPicked(null);
            }}
          >
            {t.clients.link}
          </Button>
        </Flex>
      ) : (
        <Typography.Text type="secondary">{t.clients.noLeadAccounts}</Typography.Text>
      )}
      {manual ? (
        <LinkById pending={pending} onLink={onLink} />
      ) : (
        <Button
          type="link"
          size="small"
          className="self-start"
          onClick={() => {
            setManual(true);
          }}
        >
          {t.clients.enterIdManually}
        </Button>
      )}
    </Flex>
  );
}

/** Telegram клиента: подтверждённые аккаунты, кандидаты из лидов, привязка по ID. */
export function ClientTelegram({ data, canWrite }: { data: ClientDetail; canWrite: boolean }) {
  const act = useTelegramAction(data.id);
  const confirmDanger = useConfirmDanger();
  const link = (tgUserId: number) => {
    act.mutate({ kind: "link", tgUserId });
  };
  const unlink = (i: IdentityOut) => {
    confirmDanger({
      title: t.clients.unlinkTitle.replace("{account}", identityLabel(i)),
      content: t.clients.unlinkHint,
      okText: t.clients.unlink,
      onOk: () => act.mutateAsync({ kind: "unlink", tgUserId: i.tg_user_id }),
    });
  };
  return (
    <Flex vertical gap="small">
      <Typography.Text type="secondary">{t.clients.telegramHint}</Typography.Text>
      <Identities items={data.identities} canWrite={canWrite} onAction={unlink} />
      {canWrite ? (
        <LinkPicker candidates={data.candidates} pending={act.isPending} onLink={link} />
      ) : null}
    </Flex>
  );
}
