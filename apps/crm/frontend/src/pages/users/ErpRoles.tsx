import { Alert, Checkbox, Flex, Form, Modal, Tag, Typography } from "antd";

import type { UserOut } from "../../api/generated/model";
import { erpRoleLabel, erpRoleOptions, erpRolesOf, isErpSuperuser } from "../../domain/erpRoles";
import { t } from "../../i18n/ru";

const OPTIONS = erpRoleOptions().map((option) => ({
  value: option.value,
  label: (
    <Flex vertical>
      <span>{option.label}</span>
      <Typography.Text type="secondary">{option.hint}</Typography.Text>
    </Flex>
  ),
}));

/**
 * Выбор системных ролей ERP (FIX-63): шесть ролей списком флажков — название и под ним, что роль разрешает.
 * Используется внутри `Form` (поле `erp_role_codes`) и в диалоге выдачи доступа.
 */
export function ErpRolesField({ disabled = false }: { disabled?: boolean }) {
  return (
    <Form.Item
      name="erp_role_codes"
      label={t.userAdmin.erpRoles}
      extra={disabled ? t.userAdmin.erpRolesAdmin : t.userAdmin.erpRolesHint}
    >
      <RolesGroup disabled={disabled} />
    </Form.Item>
  );
}

/** Управляемое поле формы: группа флажков с именем «Роли в ERP» (antd не пропускает `role` в `Checkbox.Group`). */
function RolesGroup({
  value,
  onChange,
  disabled,
}: {
  value?: string[] | undefined;
  onChange?: ((codes: string[]) => void) | undefined;
  disabled: boolean;
}) {
  return (
    <div role="group" aria-label={t.userAdmin.erpRoles}>
      <Checkbox.Group
        value={value ?? []}
        onChange={(codes) => {
          onChange?.(codes);
        }}
        disabled={disabled}
        options={OPTIONS}
        className="erp-roles"
      />
    </div>
  );
}

type GrantProps = {
  /** Кому выдаётся доступ; `null` — диалог закрыт. */
  user: UserOut | null;
  saving: boolean;
  onCancel: () => void;
  /** Выбранные роли ERP (может быть пусто). */
  onSubmit: (roleCodes: string[]) => void;
};

/** «Выдать доступ к ERP»: до выдачи админ выбирает роли бэк-офиса (Q-FIX50-1 (1)). */
export function ErpGrantDialog({ user, saving, onCancel, onSubmit }: GrantProps) {
  const [form] = Form.useForm<{ erp_role_codes: string[] }>();
  return (
    <Modal
      open={user !== null}
      title={user ? t.userAdmin.erpGrantTitle.replace("{name}", user.full_name) : null}
      confirmLoading={saving}
      onCancel={onCancel}
      onOk={() => {
        form.submit();
      }}
      okText={t.userAdmin.erpGrantOk}
      cancelText={t.actions.cancel}
      destroyOnHidden
    >
      {user ? (
        <Form
          form={form}
          layout="vertical"
          initialValues={{ erp_role_codes: erpRolesOf(user) }}
          onFinish={(values) => {
            onSubmit(isErpSuperuser(user) ? [] : values.erp_role_codes);
          }}
        >
          <Alert type="info" showIcon message={t.userAdmin.erpGrantHint} className="mb-16" />
          <ErpRolesField disabled={isErpSuperuser(user)} />
        </Form>
      ) : null}
    </Modal>
  );
}

/** Выданные роли ERP тегами под переключателем доступа (в таблице пользователей). */
export function ErpRoleTags({ user }: { user: UserOut }) {
  if (isErpSuperuser(user)) return <Tag color="blue">{t.userAdmin.erpRolesAdminTag}</Tag>;
  const codes = erpRolesOf(user);
  if (codes.length === 0) return null;
  return (
    <Flex gap={4} wrap>
      {codes.map((code) => (
        <Tag key={code}>{erpRoleLabel(code)}</Tag>
      ))}
    </Flex>
  );
}
