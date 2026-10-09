import { Alert, Form, Input, InputNumber, Modal, Select, Switch, Typography } from "antd";

import type { UserCreate, UserOut, UserUpdate } from "../../api/generated/model";
import { t } from "../../i18n/ru";

const ROLE_OPTIONS = ["admin", "manager", "viewer"].map((value) => ({
  value,
  label: t.roles[value] ?? value,
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
      okText={t.actions.confirm}
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
  onCancel: () => void;
  onSubmit: (values: UserUpdate) => void;
};

export function EditUserDialog({ user, saving, onCancel, onSubmit }: EditProps) {
  const [form] = Form.useForm<UserUpdate>();
  return (
    <Modal
      open={user !== null}
      title={user?.email}
      confirmLoading={saving}
      onCancel={onCancel}
      onOk={() => {
        form.submit();
      }}
      okText={t.actions.confirm}
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
            <InputNumber style={{ width: "100%" }} min={1} />
          </Form.Item>
          <Form.Item name="is_active" label={t.users.active} valuePropName="checked">
            <Switch />
          </Form.Item>
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
