import { Alert, App, Button, Form, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { RoleCode } from "../../app/rbac.generated";
import { modulesOfRoles } from "../../entities/employee/access";
import { erpConsequence } from "../../entities/employee/consequence";
import { employeeErrorText } from "../../entities/employee/errors";
import { ApiError } from "../../shared/api/errors";
import type { Employee } from "../../shared/api/generated/model";
import { findModule } from "../../modules/registry";
import { Consequence } from "../../shared/ui/Consequence";
import { RoleCheckboxes } from "../assign-role/RoleCheckboxes";
import { useEmployeeInvite } from "../assign-role/useEmployeeMutations";

import "../assign-role/assign-role.css";

interface Values {
  name: string;
  email: string;
  position?: string;
}

export interface InviteEmployeeFormProps {
  /** Сотрудник создан и письмо ушло: страница открывает его карточку */
  onInvited: (employee: Employee) => void;
  /** Сотрудник создан, но письмо не ушло: карточка по id из ошибки */
  onOpenCard: (employeeId: string) => void;
  onCancel: () => void;
}

/**
 * Приглашение по почте (SPEC-v3 §7.6): имя, почта, должность, роли. BFF создаёт пользователя в CRM с ролями и просит
 * CRM отправить письмо с временным паролем; пароль в браузер не приходит. Главная кнопка — «Отправить приглашение»
 * с блоком «Что произойдёт».
 */
export function InviteEmployeeForm({ onInvited, onOpenCard, onCancel }: InviteEmployeeFormProps) {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const [form] = Form.useForm<Values>();
  const noteId = useId();
  const [roles, setRoles] = useState<RoleCode[]>([]);
  const [rolesTouched, setRolesTouched] = useState(false);
  const [notSent, setNotSent] = useState<{ id: string; crmDown: boolean } | null>(null);
  const invite = useEmployeeInvite((employee) => {
    void message.success(t("admin.org.invite.sent", { email: employee.email }));
    onInvited(employee);
  });

  const submit = (values: Values) => {
    setRolesTouched(true);
    if (roles.length === 0) return;
    setNotSent(null);
    invite.mutate(
      {
        data: {
          email: values.email.trim(),
          name: values.name.trim(),
          ...(values.position?.trim() ? { position: values.position.trim() } : {}),
          roles,
        },
      },
      {
        onError: (error) => {
          if (error instanceof ApiError && error.code === "EMAIL_EXISTS") {
            form.setFields([{ name: "email", errors: [t("admin.org.errors.EMAIL_EXISTS")] }]);
          } else if (error instanceof ApiError && error.details["invite"] === "not_sent") {
            const id = error.details["employee_id"];
            setNotSent({
              id: typeof id === "string" ? id : "",
              crmDown: error.code === "BACKEND_UNAVAILABLE",
            });
          }
        },
      },
    );
  };

  const modules = modulesOfRoles(roles).map((code) => findModule(code)?.name ?? code);
  const erpLine = erpConsequence(t, roles);
  const items = [
    t("admin.org.invite.consequenceMail"),
    ...(modules.length > 0
      ? [t("admin.org.consequence.modules", { modules: modules.join(", ") })]
      : []),
    ...(erpLine ? [erpLine] : []),
    t("admin.org.invite.consequenceListed"),
  ];
  const showRoleNote = rolesTouched && roles.length === 0;
  const fieldError =
    invite.isError &&
    !(invite.error instanceof ApiError && invite.error.code === "EMAIL_EXISTS") &&
    notSent === null;

  return (
    <Form<Values>
      form={form}
      layout="vertical"
      onFinish={submit}
      onFinishFailed={() => {
        setRolesTouched(true);
      }}
      className="pf-panel-stack"
      style={{ gap: 16 }}
    >
      <Form.Item
        name="name"
        label={t("admin.org.invite.name")}
        rules={[{ required: true, whitespace: true, message: t("admin.org.invite.nameRequired") }]}
        style={{ margin: 0 }}
      >
        <Input maxLength={120} autoComplete="off" />
      </Form.Item>
      <Form.Item
        name="email"
        label={t("admin.org.invite.email")}
        rules={[
          { required: true, whitespace: true, message: t("admin.org.invite.emailRequired") },
          { type: "email", message: t("admin.org.invite.emailInvalid") },
        ]}
        style={{ margin: 0 }}
      >
        <Input type="email" maxLength={254} autoComplete="off" inputMode="email" />
      </Form.Item>
      <Form.Item
        name="position"
        label={t("admin.org.invite.position")}
        rules={[{ max: 120 }]}
        required={false}
        style={{ margin: 0 }}
      >
        <Input maxLength={120} autoComplete="off" />
      </Form.Item>
      <RoleCheckboxes
        value={roles}
        onChange={(next) => {
          setRoles(next);
          setRolesTouched(true);
        }}
        note={showRoleNote ? { id: noteId, text: t("admin.org.invite.needRole") } : null}
      />
      {notSent !== null ? (
        <Alert
          type="warning"
          showIcon
          role="alert"
          message={t(
            notSent.crmDown ? "admin.org.invite.notSentUnavailable" : "admin.org.invite.notSent",
          )}
          action={
            notSent.id ? (
              <Button
                size="small"
                onClick={() => {
                  onOpenCard(notSent.id);
                }}
              >
                {t("admin.org.invite.openCard")}
              </Button>
            ) : null
          }
        />
      ) : null}
      {fieldError ? (
        <Alert type="error" showIcon role="alert" message={employeeErrorText(t, invite.error)} />
      ) : null}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Button type="primary" htmlType="submit" block loading={invite.isPending}>
          {t("admin.org.invite.submit")}
        </Button>
        <Button block onClick={onCancel}>
          {t("admin.org.invite.cancel")}
        </Button>
      </div>
      <Consequence items={items} />
    </Form>
  );
}
