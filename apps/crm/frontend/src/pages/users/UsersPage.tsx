import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button } from "antd";
import { useState } from "react";

import { createUser, resetPassword, updateUser } from "../../api/generated/crm";
import type { UserCreate, UserOut, UserUpdate } from "../../api/generated/model";
import { keys, useUsers } from "../../api/queries";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useConfirmDanger } from "../../hooks/useConfirmDanger";
import { t } from "../../i18n/ru";
import { CreateUserDialog, EditUserDialog, TemporaryPassword } from "./UserDialogs";
import { transferNeeded } from "./transfer";
import { UsersTable } from "./UsersTable";
import "../admin.css";

const named = (text: string, name: string) => text.replace("{name}", name);

function useUserMutations(on: {
  created: () => void;
  updated: () => void;
  password: (value: string) => void;
  transfer: (count: number | null) => void;
}) {
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const refresh = () => client.invalidateQueries({ queryKey: keys.users });
  return {
    create: useMutation({
      mutationFn: async (values: UserCreate) => await createUser(values),
      onSuccess: (result, values) => {
        on.created();
        on.password(result.temporary_password);
        void message.success(named(t.userAdmin.created, values.full_name));
        void refresh();
      },
      onError,
    }),
    update: useMutation({
      mutationFn: async ({ user, values }: { user: UserOut; values: UserUpdate }) =>
        await updateUser(user.id, values),
      onSuccess: (_, { user, values }) => {
        on.updated();
        void message.success(named(t.userAdmin.updated, values.full_name ?? user.full_name));
        void refresh();
      },
      // Сотрудник ведёт лидов: вместо тоста — выбор коллеги в том же диалоге (ADR-0015).
      onError: (error) => {
        const count = transferNeeded(error);
        on.transfer(count);
        if (count === null) onError(error);
      },
    }),
    reset: useMutation({
      mutationFn: async (user: UserOut) => await resetPassword(user.id),
      onSuccess: (result, user) => {
        on.password(result.temporary_password);
        void message.success(named(t.userAdmin.passwordReset, user.full_name));
      },
      onError,
    }),
  };
}

type Mutations = ReturnType<typeof useUserMutations>;
type DialogsProps = {
  creating: boolean;
  editing: UserOut | null;
  transfer: number | null;
  password: string | null;
  m: Mutations;
  close: () => void;
};

function Dialogs({ creating, editing, transfer, password, m, close }: DialogsProps) {
  return (
    <>
      <CreateUserDialog
        open={creating}
        saving={m.create.isPending}
        onCancel={() => {
          close();
        }}
        onSubmit={(values) => {
          m.create.mutate(values);
        }}
      />
      <EditUserDialog
        user={editing}
        saving={m.update.isPending}
        transferRequired={transfer}
        onCancel={() => {
          close();
        }}
        onSubmit={(values) => {
          if (editing) m.update.mutate({ user: editing, values });
        }}
      />
      <TemporaryPassword
        password={password}
        onClose={() => {
          close();
        }}
      />
    </>
  );
}

/** Пользователи (admin, SPEC §10.1): создание с временным паролем, роли, деактивация, сброс. */
export function UsersPage() {
  const query = useUsers();
  const confirmDanger = useConfirmDanger();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<UserOut | null>(null);
  const [password, setPassword] = useState<string | null>(null);
  const [transfer, setTransfer] = useState<number | null>(null);
  const edit = (u: UserOut | null) => {
    setEditing(u);
    setTransfer(null);
  };
  const m = useUserMutations({
    created: () => {
      setCreating(false);
    },
    updated: () => {
      edit(null);
    },
    password: setPassword,
    transfer: setTransfer,
  });
  const reset = (u: UserOut) => {
    confirmDanger({
      title: named(t.confirm.resetPassword, u.full_name),
      content: t.confirm.resetPasswordHint,
      okText: t.confirm.reset,
      onOk: () => m.reset.mutateAsync(u),
    });
  };
  const create = (
    <Button
      type="primary"
      onClick={() => {
        setCreating(true);
      }}
    >
      {t.users.create}
    </Button>
  );

  return (
    <PageBody>
      <PageHeader title={t.page.users} extra={create} />
      <PageState query={query}>
        <UsersTable data={query.data ?? []} loading={false} onEdit={edit} onReset={reset} />
      </PageState>
      <Dialogs
        creating={creating}
        editing={editing}
        transfer={transfer}
        password={password}
        m={m}
        close={() => {
          setCreating(false);
          edit(null);
          setPassword(null);
        }}
      />
    </PageBody>
  );
}
