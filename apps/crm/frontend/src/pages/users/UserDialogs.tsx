import { Alert, Form, Input, InputNumber, Modal, Select, Switch, Typography } from "antd";

import type { UserCreate, UserOut, UserUpdate } from "../../api/generated/model";
import { useTeam } from "../../api/queries";
import { t } from "../../i18n/ru";
import { roleLabel } from "../../domain/labels";

const ROLE_OPTIONS = ["admin", "manager", "viewer"].map((value) => ({
  value,
  label: roleLabel(value),
}));

type CreateProps = {
  open: boolean;
  saving: boolean;
  onCancel: () => void;
  onSubmit: (values: UserCreate) => void;
};

export function CreateUserDialog({ open, saving, onCancel, onSubmit }: CreateProps) {
  const [form] = Form.useForm<UserCreate>();
  return (
    <Modal
      open={open}
      title={t.users.create}
      confirmLoading={saving}
      onCancel={onCancel}
      onOk={() => {
        form.submit();
      }}
      okText={t.userAdmin.createOk}
      cancelText={t.actions.cancel}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={onSubmit}
        initialValues={{ roles: ["manager"] }}
      >
        <Form.Item name="email" label={t.users.email} rules={[{ required: true, type: "email" }]}>
          <Input />
        </Form.Item>
        <Form.Item name="full_name" label={t.users.fullName} rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="roles" label={t.users.roles} rules={[{ required: true }]}>
          <Select mode="multiple" options={ROLE_OPTIONS} />
        </Form.Item>
      </Form>
    </Modal>
  );
}

type EditProps = {
  user: UserOut | null;
  saving: boolean;
  /** Бэкенд потребовал передать лидов (число; 0 — неизвестно), `null` — не требовал. */
  transferRequired?: number | null;
  onCancel: () => void;
  onSubmit: (values: UserUpdate) => void;
};

export function EditUserDialog({
  user,
  saving,
  transferRequired = null,
  onCancel,
  onSubmit,
}: EditProps) {
  const mustTransfer = transferRequired !== null;
  const [form] = Form.useForm<UserUpdate>();
  const active = Form.useWatch("is_active", form);
  const team = useTeam();
  const colleagues = (team.data ?? [])
    .filter((m) => m.id !== user?.id)
    .map((m) => ({ value: m.id, label: m.full_name }));
  return (
    <Modal
      open={user !== null}
      title={user ? t.userAdmin.editTitle.replace("{name}", user.full_name) : null}
      confirmLoading={saving}
      onCancel={onCancel}
      onOk={() => {
        form.submit();
      }}
      okText={t.common.save}
      cancelText={t.actions.cancel}
      destroyOnHidden
    >
      {user ? (
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            full_name: user.full_name,
            roles: user.roles,
            is_active: user.is_active,
            tg_user_id: user.tg_user_id,
          }}
          onFinish={(values) => {
            onSubmit({ ...values, clear_tg_user_id: values.tg_user_id == null });
          }}
        >
          <Form.Item name="full_name" label={t.users.fullName} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="roles" label={t.users.roles} rules={[{ required: true }]}>
            <Select mode="multiple" options={ROLE_OPTIONS} />
          </Form.Item>
          <Form.Item name="tg_user_id" label={t.users.telegram}>
            <InputNumber className="full-width" min={1} />
          </Form.Item>
          <Form.Item name="is_active" label={t.users.active} valuePropName="checked">
            <Switch />
          </Form.Item>
          {mustTransfer ? (
            <Alert
              type="warning"
              showIcon
              message={t.users.transferRequired}
              description={t.users.transferRequiredHint.replace(
                "{count}",
                transferRequired ? String(transferRequired) : "—",
              )}
            />
          ) : null}
          {(user.is_active && active === false) || mustTransfer ? (
            <Form.Item
              name="transfer_to_user_id"
              label={mustTransfer ? t.users.transferRequired : t.users.transferTo}
              extra={t.users.transferHint}
              rules={mustTransfer ? [{ required: true }] : []}
            >
              <Select allowClear showSearch optionFilterProp="label" options={colleagues} />
            </Form.Item>
          ) : null}
        </Form>
      ) : null}
    </Modal>
  );
}

export function TemporaryPassword({
  password,
  onClose,
}: {
  password: string | null;
  onClose: () => void;
}) {
  return (
    <Modal
      open={password !== null}
      title={t.users.temporary}
      onOk={onClose}
      onCancel={onClose}
      footer={null}
    >
      <Typography.Paragraph copyable code>
        {password}
      </Typography.Paragraph>
      <Alert type="warning" showIcon message={t.users.copy} />
    </Modal>
  );
}
