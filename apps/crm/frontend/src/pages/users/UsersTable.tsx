import { Button, Space, Switch, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { UserOut } from "../../api/generated/model";
import { BooleanTag } from "../../components/BooleanTag";
import { ActionsTitle, RowActions } from "../../components/RowActions";
import { roleLabel } from "../../domain/labels";
import { hasErpAccess } from "../../domain/platformAccess";
import { t } from "../../i18n/ru";
import { ErpRoleTags } from "./ErpRoles";

type Handlers = {
  onEdit: (u: UserOut) => void;
  onReset: (u: UserOut) => void;
  onInvite: (u: UserOut) => void;
  onResetByEmail: (u: UserOut) => void;
  /** Выдать (`true`) или снять (`false`) доступ к ERP. */
  onToggleErp: (u: UserOut, enabled: boolean) => void;
  /** Пользователь, чей переключатель сейчас сохраняется. */
  erpPendingId?: number | null;
};

const named = (text: string, u: UserOut) => text.replace("{name}", u.full_name);

function TelegramTag({ id }: { id: number | null }) {
  if (id === null) return <Tag>{t.userAdmin.tgNotLinked}</Tag>;
  return (
    <Tooltip title={`${t.users.telegram}: ${String(id)}`}>
      <Tag color="green">{t.userAdmin.tgLinked}</Tag>
    </Tooltip>
  );
}

function columns({
  onEdit,
  onReset,
  onInvite,
  onResetByEmail,
  onToggleErp,
  erpPendingId,
}: Handlers): ColumnsType<UserOut> {
  return [
    {
      title: t.users.fullName,
      render: (_, u) => (
        <Space direction="vertical" size={0}>
          <Button
            type="link"
            className="link-button"
            onClick={() => {
              onEdit(u);
            }}
          >
            {u.full_name}
          </Button>
          <Typography.Text type="secondary">{u.email}</Typography.Text>
        </Space>
      ),
    },
    {
      title: t.users.roles,
      render: (_, u) => u.roles.map((r) => <Tag key={r}>{roleLabel(r)}</Tag>),
    },
    {
      title: t.userAdmin.status,
      render: (_, u) => (
        <BooleanTag value={u.is_active} yes={t.userAdmin.active} no={t.userAdmin.inactive} />
      ),
    },
    {
      title: (
        <Tooltip title={t.userAdmin.erpAccessHint}>
          <span>{t.userAdmin.erpAccess}</span>
        </Tooltip>
      ),
      render: (_, u) => (
        <Space direction="vertical" size={4}>
          <Tooltip title={u.is_active || hasErpAccess(u) ? null : t.userAdmin.erpInactive}>
            <Switch
              checked={hasErpAccess(u)}
              disabled={(!u.is_active && !hasErpAccess(u)) || erpPendingId === u.id}
              loading={erpPendingId === u.id}
              aria-label={named(t.userAdmin.erpSwitchLabel, u)}
              onChange={(checked) => {
                onToggleErp(u, checked);
              }}
            />
          </Tooltip>
          {hasErpAccess(u) ? <ErpRoleTags user={u} /> : null}
        </Space>
      ),
    },
    { title: t.users.telegram, render: (_, u) => <TelegramTag id={u.tg_user_id} /> },
    {
      title: <ActionsTitle />,
      className: "col-actions",
      render: (_, u) => (
        <RowActions
          label={named(t.userAdmin.rowActions, u)}
          actions={[
            {
              key: "edit",
              label: t.users.edit,
              onClick: () => {
                onEdit(u);
              },
            },
            {
              key: "invite",
              label: t.users.invite,
              disabled: !u.is_active,
              onClick: () => {
                onInvite(u);
              },
            },
            {
              key: "reset",
              label: t.users.resetPassword,
              danger: true,
              onClick: () => {
                onReset(u);
              },
            },
            {
              key: "reset-email",
              label: t.users.resetByEmail,
              danger: true,
              disabled: !u.is_active,
              onClick: () => {
                onResetByEmail(u);
              },
            },
          ]}
        />
      ),
    },
  ];
}

/** Пользователи: имя — открывает редактирование, сброс пароля — в меню «⋯». */
export function UsersTable({
  data,
  loading,
  ...h
}: Handlers & { data: UserOut[]; loading: boolean }) {
  return (
    <Table<UserOut>
      sticky
      rowKey="id"
      loading={loading}
      dataSource={data}
      scroll={{ x: 640 }}
      pagination={false}
      rowClassName={(u) => (u.is_active ? "" : "row-muted")}
      columns={columns(h)}
    />
  );
}
