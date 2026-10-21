import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button } from "antd";
import { useState } from "react";

import {
  createUser,
  inviteUser,
  resetPassword,
  resetPasswordByEmail,
  updateUser,
} from "../../api/generated/crm";
import type { UserCreate, UserOut, UserUpdate } from "../../api/generated/model";
import { withErpAccess } from "../../domain/platformAccess";
import { emailLogKey } from "../../api/integrationQueries";
import { keys, useUsers } from "../../api/queries";
import { PageBody } from "../../components/PageBody";
import { PageHeader } from "../../components/PageHeader";
import { PageState } from "../../components/PageState";
import { useApiErrorToast } from "../../hooks/useApiErrorToast";
import { useConfirmDanger } from "../../hooks/useConfirmDanger";
import { t } from "../../i18n/ru";
import { ErpGrantDialog } from "./ErpRoles";
import { CreateUserDialog, EditUserDialog, TemporaryPassword } from "./UserDialogs";
import { transferNeeded } from "./transfer";
import { UsersTable } from "./UsersTable";
import "../admin.css";

type ErpRoleCodes = NonNullable<UserUpdate["erp_role_codes"]>;

const named = (text: string, name: string) => text.replace("{name}", name);

/** Временный пароль показан после создания или сброса; `user` — кому можно сразу выслать письмо. */
type Shown = { password: string; user: UserOut } | null;

function useUserMutations(on: {
  created: () => void;
  updated: () => void;
  password: (value: Shown) => void;
  transfer: (count: number | null) => void;
  granted: () => void;
}) {
  const client = useQueryClient();
  const { message } = AntApp.useApp();
  const onError = useApiErrorToast();
  const refresh = () => client.invalidateQueries({ queryKey: keys.users });
  const refreshMail = () => client.invalidateQueries({ queryKey: emailLogKey() });
  return {
    create: useMutation({
      mutationFn: async (values: UserCreate) => await createUser(values),
      onSuccess: (result, values) => {
        on.created();
        on.password({ password: result.temporary_password, user: result.user });
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
        on.password({ password: result.temporary_password, user });
        void message.success(named(t.userAdmin.passwordReset, user.full_name));
      },
      onError,
    }),
    // Доступ к ERP (FIX-11): ответ — «принято»; создание учётной записи и ошибки ERP идут в фоне
    // (центр внешних сервисов), пользователю админа они не показываются.
    // Выдача несёт выбранные роли ERP (FIX-63, `roleCodes`): доступ и роли — одним запросом, одним провижинингом.
    erp: useMutation({
      mutationFn: async ({
        user,
        enabled,
        roleCodes,
      }: {
        user: UserOut;
        enabled: boolean;
        roleCodes?: string[];
      }) =>
        await updateUser(user.id, {
          platform_access: withErpAccess(enabled),
          ...(enabled && roleCodes ? { erp_role_codes: roleCodes as ErpRoleCodes } : {}),
        }),
      onSuccess: (_, { user, enabled }) => {
        on.granted();
        void message.success(
          named(enabled ? t.userAdmin.erpGranted : t.userAdmin.erpRevoked, user.full_name),
        );
        void refresh();
      },
      onError,
    }),
    // Письма через коннектор «Почта» (M3-CRM-08): без SMTP бэкенд отвечает 409 с подсказкой.
    invite: useMutation({
      mutationFn: async (user: UserOut) => await inviteUser(user.id),
      onSuccess: (_, user) => {
        on.password(null);
        void message.success(named(t.users.invited, user.full_name));
        void refreshMail();
      },
      onError,
    }),
    resetByEmail: useMutation({
      mutationFn: async (user: UserOut) => await resetPasswordByEmail(user.id),
      onSuccess: (_, user) => {
        void message.success(named(t.users.passwordEmailed, user.full_name));
        void refreshMail();
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
  shown: Shown;
  m: Mutations;
  close: () => void;
};

function Dialogs({ creating, editing, transfer, shown, m, close }: DialogsProps) {
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
        password={shown?.password ?? null}
        email={shown?.user.email ?? ""}
        inviting={m.invite.isPending}
        onInvite={() => {
          if (shown) m.invite.mutate(shown.user);
        }}
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
  const [shown, setShown] = useState<Shown>(null);
  const [transfer, setTransfer] = useState<number | null>(null);
  const [granting, setGranting] = useState<UserOut | null>(null);
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
    password: setShown,
    transfer: setTransfer,
    granted: () => {
      setGranting(null);
    },
  });
  const reset = (u: UserOut) => {
    confirmDanger({
      title: named(t.confirm.resetPassword, u.full_name),
      content: t.confirm.resetPasswordHint,
      okText: t.confirm.reset,
      onOk: () => m.reset.mutateAsync(u),
    });
  };
  const invite = (u: UserOut) => {
    confirmDanger({
      title: named(t.confirm.inviteUser, u.full_name),
      content: t.confirm.inviteUserHint,
      okText: t.confirm.invite,
      onOk: () => m.invite.mutateAsync(u),
    });
  };
  const resetByEmail = (u: UserOut) => {
    confirmDanger({
      title: named(t.confirm.resetByEmail, u.full_name),
      content: t.confirm.resetByEmailHint,
      okText: t.confirm.reset,
      onOk: () => m.resetByEmail.mutateAsync(u),
    });
  };
  const toggleErp = (u: UserOut, enabled: boolean) => {
    if (enabled) {
      setGranting(u); // сначала выбор ролей ERP, потом выдача (FIX-63)
      return;
    }
    confirmDanger({
      title: named(t.userAdmin.erpRevokeTitle, u.full_name),
      content: t.userAdmin.erpRevokeHint,
      okText: t.userAdmin.erpRevoke,
      onOk: () => m.erp.mutateAsync({ user: u, enabled }),
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
        <UsersTable
          data={query.data ?? []}
          loading={false}
          onEdit={edit}
          onReset={reset}
          onInvite={invite}
          onResetByEmail={resetByEmail}
          onToggleErp={toggleErp}
          erpPendingId={m.erp.isPending ? m.erp.variables.user.id : null}
        />
      </PageState>
      <ErpGrantDialog
        user={granting}
        saving={m.erp.isPending}
        onCancel={() => {
          setGranting(null);
        }}
        onSubmit={(roleCodes) => {
          if (granting) m.erp.mutate({ user: granting, enabled: true, roleCodes });
        }}
      />
      <Dialogs
        creating={creating}
        editing={editing}
        transfer={transfer}
        shown={shown}
        m={m}
        close={() => {
          setCreating(false);
          edit(null);
          setShown(null);
        }}
      />
    </PageBody>
  );
}
