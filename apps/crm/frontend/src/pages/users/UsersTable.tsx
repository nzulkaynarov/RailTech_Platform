import { Button, Space, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { UserOut } from "../../api/generated/model";
import { BooleanTag } from "../../components/BooleanTag";
import { ActionsTitle, RowActions } from "../../components/RowActions";
import { roleLabel } from "../../domain/labels";
import { t } from "../../i18n/ru";

type Handlers = { onEdit: (u: UserOut) => void; onReset: (u: UserOut) => void };

const named = (text: string, u: UserOut) => text.replace("{name}", u.full_name);

function TelegramTag({ id }: { id: number | null }) {
  if (id === null) return <Tag>{t.userAdmin.tgNotLinked}</Tag>;
  return (
    <Tooltip title={`${t.users.telegram}: ${String(id)}`}>
      <Tag color="green">{t.userAdmin.tgLinked}</Tag>
    </Tooltip>
  );
}

function columns({ onEdit, onReset }: Handlers): ColumnsType<UserOut> {
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
              key: "reset",
              label: t.users.resetPassword,
              danger: true,
              onClick: () => {
                onReset(u);
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
