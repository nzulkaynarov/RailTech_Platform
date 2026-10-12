import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Card, Flex, List, Space, Tag, Typography } from "antd";
import { useState } from "react";

import { adminKeys, useClientContacts } from "../../api/adminQueries";
import { createClientContact, deleteClientContact } from "../../api/generated/crm";
import type { ContactOut, ContactSuggestion } from "../../api/generated/model";
import { unwrap } from "../../api/http";
import { EmptyState } from "../../components/EmptyState";
import { RowActions } from "../../components/RowActions";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useConfirmDanger } from "../../hooks/useConfirmDanger";
import { t } from "../../i18n/ru";
import { ContactDialog } from "./ContactDialog";
import { fromSuggestion } from "./contactForm";

type Dialog = { open: boolean; contact: ContactOut | null };

function ContactLine({ c }: { c: ContactOut }) {
  return (
    <Flex vertical gap={2} className="contact-line">
      <Space wrap size="small">
        <Typography.Text strong>{c.full_name}</Typography.Text>
        {c.position ? <Typography.Text type="secondary">{c.position}</Typography.Text> : null}
        {c.is_primary ? <Tag color="blue">{t.contacts.primary}</Tag> : null}
        {c.telegram_identity_id ? <Tag>{t.contacts.telegram}</Tag> : null}
      </Space>
      <Space wrap size="middle">
        {c.phone_e164 ? <a href={`tel:${c.phone_e164}`}>{c.phone_e164}</a> : null}
        {c.email ? <a href={`mailto:${c.email}`}>{c.email}</a> : null}
      </Space>
      {c.note ? <Typography.Text type="secondary">{c.note}</Typography.Text> : null}
    </Flex>
  );
}

function useContactMutations(clientId: number) {
  const query = useQueryClient();
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const refresh = () => query.invalidateQueries({ queryKey: adminKeys.clientContacts(clientId) });
  const remove = useMutation({
    mutationFn: async (c: ContactOut) => unwrap(await deleteClientContact(clientId, c.id)),
    onSuccess: (_, c) => {
      void message.success(t.contacts.removed.replace("{name}", c.full_name));
      void refresh();
    },
    onError,
  });
  const addSuggested = useMutation({
    mutationFn: async (a: { s: ContactSuggestion; primary: boolean }) =>
      unwrap(await createClientContact(clientId, fromSuggestion(a.s, a.primary))),
    onSuccess: (_, a) => {
      void message.success(t.contacts.added.replace("{name}", a.s.full_name));
      void refresh();
    },
    onError,
  });
  return { remove, addSuggested };
}

type SuggestionsProps = {
  items: ContactSuggestion[];
  pending: boolean;
  onAdd: (s: ContactSuggestion) => void;
};

function Suggestions({ items, pending, onAdd }: SuggestionsProps) {
  if (!items.length) return null;
  return (
    <List
      size="small"
      header={
        <Flex vertical>
          <Typography.Text strong>{t.contacts.fromTelegram}</Typography.Text>
          <Typography.Text type="secondary">{t.contacts.fromTelegramHint}</Typography.Text>
        </Flex>
      }
      dataSource={items}
      renderItem={(s) => (
        <List.Item
          actions={[
            <Button
              key="add"
              size="small"
              loading={pending}
              aria-label={`${t.contacts.add}: ${s.full_name}`}
              onClick={() => {
                onAdd(s);
              }}
            >
              {t.contacts.add}
            </Button>,
          ]}
        >
          <Space wrap size="small">
            <span>{s.full_name}</span>
            <a href={`tel:${s.phone_e164}`}>{s.phone_e164}</a>
            {s.tg_username ? (
              <Typography.Text type="secondary">@{s.tg_username}</Typography.Text>
            ) : null}
          </Space>
        </List.Item>
      )}
    />
  );
}

/** Контакты клиента (Q-011): список, добавление/правка, удаление, «Добавить из Telegram» (Q-020). */
export function ClientContacts({ clientId, canWrite }: { clientId: number; canWrite: boolean }) {
  const query = useClientContacts(clientId);
  const [dialog, setDialog] = useState<Dialog>({ open: false, contact: null });
  const { remove, addSuggested } = useContactMutations(clientId);
  const confirmDanger = useConfirmDanger();
  const contacts = query.data?.contacts ?? [];
  const openNew = () => {
    setDialog({ open: true, contact: null });
  };
  const menu = (c: ContactOut) => (
    <RowActions
      key="menu"
      label={t.contacts.actions.replace("{name}", c.full_name)}
      actions={[
        {
          key: "edit",
          label: t.contacts.edit,
          onClick: () => {
            setDialog({ open: true, contact: c });
          },
        },
        {
          key: "remove",
          label: t.contacts.remove,
          danger: true,
          onClick: () => {
            confirmDanger({
              title: t.contacts.removeTitle.replace("{name}", c.full_name),
              content: t.contacts.removeHint,
              okText: t.contacts.remove,
              onOk: () => remove.mutateAsync(c),
            });
          },
        },
      ]}
    />
  );
  return (
    <Card
      size="small"
      title={t.contacts.title}
      loading={query.isLoading}
      extra={
        canWrite && contacts.length ? (
          <Button size="small" icon={<PlusOutlined />} onClick={openNew}>
            {t.contacts.add}
          </Button>
        ) : null
      }
    >
      {contacts.length ? (
        <List
          size="small"
          dataSource={contacts}
          renderItem={(c) => (
            <List.Item actions={canWrite ? [menu(c)] : []}>
              <ContactLine c={c} />
            </List.Item>
          )}
        />
      ) : (
        <EmptyState
          compact
          title={t.contacts.empty}
          hint={t.contacts.emptyHint}
          {...(canWrite ? { action: { label: t.clients.addInline, onClick: openNew } } : {})}
        />
      )}
      {canWrite ? (
        <Suggestions
          items={query.data?.suggestions ?? []}
          pending={addSuggested.isPending}
          onAdd={(s) => {
            addSuggested.mutate({ s, primary: !contacts.some((c) => c.is_primary) });
          }}
        />
      ) : null}
      <ContactDialog
        clientId={clientId}
        contact={dialog.contact}
        open={dialog.open}
        onClose={() => {
          setDialog({ open: false, contact: null });
        }}
      />
    </Card>
  );
}
