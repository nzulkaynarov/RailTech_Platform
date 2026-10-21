import { MailOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Switch,
  Typography,
} from "antd";

import type { UserCreate, UserOut, UserUpdate } from "../../api/generated/model";
import { useTeam } from "../../api/queries";
import { t } from "../../i18n/ru";
import { erpRolesOf, isErpSuperuser } from "../../domain/erpRoles";
import { roleLabel } from "../../domain/labels";
import { hasErpAccess } from "../../domain/platformAccess";
import { ErpRolesField } from "./ErpRoles";

const ROLE_OPTIONS = ["admin", "manager", "viewer"].map((value) => ({
  value,
  label: roleLabel(value),
}));

// Не `required: true`: antd тогда ставит `aria-required` на корень Select, а axe считает это критичным
// (aria-allowed-attr). Проверка та же — выбрана хотя бы одна роль.
const ROLES_RULES = [{ type: "array" as const, min: 1, message: t.userAdmin.rolesRequired }];

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
        <Form.Item name="roles" label={t.users.roles} rules={ROLES_RULES}>
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
  const rolesWatch = Form.useWatch("roles", form);
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
            erp_role_codes: erpRolesOf(user),
          }}
          onFinish={(values) => {
            // Роли ERP (FIX-63) шлём только тем, у кого есть доступ к ERP: без него поле в форме скрыто.
            const { erp_role_codes, ...rest } = values;
            onSubmit({
              ...rest,
              clear_tg_user_id: values.tg_user_id == null,
              ...(hasErpAccess(user) && !isErpSuperuser({ roles: values.roles ?? user.roles })
                ? { erp_role_codes }
                : {}),
            });
          }}
        >
          <Form.Item name="full_name" label={t.users.fullName} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="roles" label={t.users.roles} rules={ROLES_RULES}>
            <Select mode="multiple" options={ROLE_OPTIONS} />
          </Form.Item>
          {hasErpAccess(user) ? (
            <ErpRolesField disabled={isErpSuperuser({ roles: rolesWatch ?? user.roles })} />
          ) : null}
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

/**
 * Временный пароль показывается один раз; рядом — «Отправить приглашение по почте» (M3-CRM-08):
 * бэкенд выпустит новый временный пароль и отправит письмо, этот пароль перестанет действовать.
 */
export function TemporaryPassword({
  password,
  email,
  inviting = false,
  onInvite,
  onClose,
}: {
  password: string | null;
  email?: string;
  inviting?: boolean;
  onInvite?: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      open={password !== null}
      title={t.users.temporary}
      onOk={onClose}
      onCancel={onClose}
      okText={t.users.done}
      cancelButtonProps={{ style: { display: "none" } }}
      destroyOnHidden
    >
      <Typography.Paragraph copyable code>
        {password}
      </Typography.Paragraph>
      <Alert type="warning" showIcon message={t.users.copy} />
      {onInvite && email ? (
        <Flex vertical gap="small" className="mt-md">
          <Button icon={<MailOutlined aria-hidden />} loading={inviting} onClick={onInvite}>
            {t.users.invite}
          </Button>
          <Typography.Text type="secondary">
            {t.users.inviteHint.replace("{email}", email)}
          </Typography.Text>
        </Flex>
      ) : null}
    </Modal>
  );
}
