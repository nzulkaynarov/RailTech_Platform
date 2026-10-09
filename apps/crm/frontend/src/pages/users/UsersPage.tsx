import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Space, Table, Tag } from "antd";
import { useState } from "react";

import { createUser, resetPassword, updateUser } from "../../api/generated/crm";
import type { UserCreate, UserOut, UserUpdate } from "../../api/generated/model";
import { type ApiError, unwrap } from "../../api/http";
import { keys, useUsers } from "../../api/queries";
import { errorText, t } from "../../i18n/ru";
import { CreateUserDialog, EditUserDialog, TemporaryPassword } from "./UserDialogs";
import { roleLabel } from "../../domain/labels";
import { useConfirmDanger } from "../../hooks/useConfirmDanger";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";

/** Пользователи (admin, SPEC §10.1): создание с временным паролем, роли, деактивация, сброс. */
export function UsersPage() {
  const query = useUsers();
  const { data, isLoading } = query;
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const confirmDanger = useConfirmDanger();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<UserOut | null>(null);
  const [password, setPassword] = useState<string | null>(null);

  const onError = (error: unknown) => {
    void message.error(errorText((error as ApiError).code, (error as ApiError).message));
  };
  const refresh = () => client.invalidateQueries({ queryKey: keys.users });

  const create = useMutation({
    mutationFn: async (values: UserCreate) => unwrap(await createUser(values)),
    onSuccess: (result) => {
      setCreating(false);
      setPassword(result.temporary_password);
      void refresh();
    },
    onError,
  });
  const update = useMutation({
    mutationFn: async ({ id, values }: { id: number; values: UserUpdate }) =>
      unwrap(await updateUser(id, values)),
    onSuccess: () => {
      setEditing(null);
      void refresh();
    },
    onError,
  });
  const reset = useMutation({
    mutationFn: async (id: number) => unwrap(await resetPassword(id)),
    onSuccess: (result) => {
      setPassword(result.temporary_password);
    },
    onError,
  });

  return (
    <>
      <PageHeader
        title={t.page.users}
        extra={
          <Button
            type="primary"
            onClick={() => {
              setCreating(true);
            }}
          >
            {t.users.create}
          </Button>
        }
      />
      <PageState query={query} inline>
        <Table<UserOut>
          rowKey="id"
          loading={isLoading}
          dataSource={data ?? []}
          scroll={{ x: 640 }}
          pagination={false}
          columns={[
            { title: t.users.email, dataIndex: "email" },
            { title: t.users.fullName, dataIndex: "full_name" },
            {
              title: t.users.roles,
              render: (_, u) => u.roles.map((r) => <Tag key={r}>{roleLabel(r)}</Tag>),
            },
            {
              title: t.users.active,
              render: (_, u) =>
                u.is_active ? <Tag color="green">{t.common.yes}</Tag> : <Tag>{t.common.no}</Tag>,
            },
            { title: t.users.telegram, render: (_, u) => u.tg_user_id ?? t.common.none },
            {
              render: (_, u) => (
                <Space>
                  <Button
                    size="small"
                    onClick={() => {
                      setEditing(u);
                    }}
                  >
                    {t.users.edit}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      confirmDanger({
                        title: t.confirm.resetPassword.replace("{name}", u.full_name),
                        content: t.confirm.resetPasswordHint,
                        okText: t.confirm.reset,
                        onOk: () => reset.mutateAsync(u.id),
                      });
                    }}
                  >
                    {t.users.resetPassword}
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </PageState>
      <CreateUserDialog
        open={creating}
        saving={create.isPending}
        onCancel={() => {
          setCreating(false);
        }}
        onSubmit={(values) => {
          create.mutate(values);
        }}
      />
      <EditUserDialog
        user={editing}
        saving={update.isPending}
        onCancel={() => {
          setEditing(null);
        }}
        onSubmit={(values) => {
          if (editing) update.mutate({ id: editing.id, values });
        }}
      />
      <TemporaryPassword
        password={password}
        onClose={() => {
          setPassword(null);
        }}
      />
    </>
  );
}
