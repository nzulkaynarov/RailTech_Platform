import { Alert, App, Button, Form, Input, Radio, Space } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { accessOfRoleIds } from "../../entities/employee/access";
import { backendConsequence } from "../../entities/employee/consequence";
import { employeeErrorText } from "../../entities/employee/errors";
import { ApiError } from "../../shared/api/errors";
import type { Employee, EmployeeCredentials } from "../../shared/api/generated/model";
import { moduleName } from "../../modules/registry";
import { Consequence } from "../../shared/ui/Consequence";
import { lines } from "../first-run/lines";
import { TemporaryPasswordCard } from "../temporary-password/TemporaryPasswordCard";
import { useCreateEmployeeWithPassword } from "../temporary-password/useTemporaryPassword";
import { RoleCheckboxes } from "../assign-role/RoleCheckboxes";
import { useRoles } from "../assign-role/useRoles";
import { useEmployeeInvite } from "../assign-role/useEmployeeMutations";

import "../assign-role/assign-role.css";

type Delivery = "mail" | "password";

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
  /**
   * Временный пароль на экране (`true`) или передан — «Готово» (`false`). Мастер первого запуска прячет «Дальше», пока пароль
   * не передан: иначе он пропал бы вместе с формой (W15-H4).
   */
  onPasswordShown?: (shown: boolean) => void;
}

/**
 * Приглашение по почте (SPEC-v3 §7.6): имя, почта, должность, роли (из списка ролей компании, ADR-0012). BFF создаёт пользователя в CRM с ролями и просит
 * CRM отправить письмо с временным паролем; пароль в браузер не приходит. Главная кнопка — «Отправить приглашение»
 * с блоком «Что произойдёт». Форма не хранит прошлое приглашение: после результата она сбрасывается, а при повторном
 * открытии (`OrgPage` задаёт `key` по ключу навигации) создаётся заново.
 *
 * Без почты (W13-A4, BFF 0.10.0): способ «Временным паролем» создаёт сотрудника без письма и показывает пароль
 * администратору один раз (`TemporaryPasswordCard`); после «Готово» открывается карточка сотрудника.
 */
export function InviteEmployeeForm({
  onInvited,
  onOpenCard,
  onCancel,
  onPasswordShown,
}: InviteEmployeeFormProps) {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const [form] = Form.useForm<Values>();
  const noteId = useId();
  const { query: rolesQuery, roles: companyRoles } = useRoles();
  const [roles, setRoles] = useState<string[]>([]);
  const [rolesTouched, setRolesTouched] = useState(false);
  const [notSent, setNotSent] = useState<{ id: string; crmDown: boolean } | null>(null);
  const [delivery, setDelivery] = useState<Delivery>("mail");
  const deliveryId = useId();
  const [credentials, setCredentials] = useState<EmployeeCredentials | null>(null);
  const create = useCreateEmployeeWithPassword();
  const invite = useEmployeeInvite((employee) => {
    void message.success(t("admin.org.invite.sent", { email: employee.email }));
    reset();
    onInvited(employee);
  });

  /** После результата форма пустая: поля, роли и ошибки не переходят в следующее приглашение (QA-P1-D-3). */
  function reset() {
    form.resetFields();
    setRoles([]);
    setRolesTouched(false);
    setNotSent(null);
    setDelivery("mail");
    setCredentials(null);
    create.reset();
  }

  const submit = (values: Values) => {
    setRolesTouched(true);
    if (roles.length === 0) return;
    setNotSent(null);
    const data = {
      email: values.email.trim(),
      name: values.name.trim(),
      ...(values.position?.trim() ? { position: values.position.trim() } : {}),
      role_ids: roles,
    };
    if (delivery === "password") {
      create.mutate(
        { data },
        {
          onSuccess: (created) => {
            // Пароль есть только здесь: в состоянии формы, пока администратор его не передал.
            setCredentials(created);
            onPasswordShown?.(true);
            create.reset();
          },
          onError: (error) => {
            if (error instanceof ApiError && error.code === "EMAIL_EXISTS") {
              form.setFields([{ name: "email", errors: [t("admin.org.errors.EMAIL_EXISTS")] }]);
            }
          },
        },
      );
      return;
    }
    invite.mutate(
      { data },
      {
        onError: (error) => {
          if (error instanceof ApiError && error.code === "EMAIL_EXISTS") {
            form.setFields([{ name: "email", errors: [t("admin.org.errors.EMAIL_EXISTS")] }]);
          } else if (error instanceof ApiError && error.details["invite"] === "not_sent") {
            const id = error.details["employee_id"];
            // Сотрудник уже создан: повторная отправка с теми же данными даст «такая почта уже есть».
            reset();
            setNotSent({
              id: typeof id === "string" ? id : "",
              crmDown: error.code === "BACKEND_UNAVAILABLE",
            });
          }
        },
      },
    );
  };

  const access = accessOfRoleIds(companyRoles, roles);
  const modules = access.modules.map((code) => moduleName(t, code));
  const items = [
    ...(delivery === "password"
      ? lines(t, "admin.org.invite.consequencePassword").slice(0, 2)
      : [t("admin.org.invite.consequenceMail")]),
    ...(modules.length > 0
      ? [t("admin.org.consequence.modules", { modules: modules.join(", ") })]
      : []),
    ...(roles.length > 0 ? backendConsequence(t, access) : []),
    ...(delivery === "password"
      ? lines(t, "admin.org.invite.consequencePassword").slice(2)
      : [t("admin.org.invite.consequenceListed")]),
  ];
  const showRoleNote = rolesTouched && roles.length === 0;
  const failed = delivery === "password" ? create : invite;
  const fieldError =
    failed.isError &&
    !(failed.error instanceof ApiError && failed.error.code === "EMAIL_EXISTS") &&
    notSent === null;

  if (credentials !== null) {
    return (
      <TemporaryPasswordCard
        employee={credentials.employee}
        password={credentials.temporary_password}
        onDone={() => {
          const { employee } = credentials;
          onPasswordShown?.(false);
          void message.success(t("admin.org.invite.created", { email: employee.email }));
          // Форма размонтируется вместе с боковым окном: сбрасывать её поля уже не нужно.
          onInvited(employee);
        }}
      />
    );
  }

  return (
    <Form<Values>
      // Своё имя формы — свои id полей: в мастере первого запуска рядом бывает форма компании с теми же полями
      name="invite-employee"
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
      <div role="radiogroup" aria-labelledby={deliveryId}>
        <span id={deliveryId} style={{ display: "block", fontWeight: 600, marginBottom: 4 }}>
          {t("admin.org.invite.delivery")}
        </span>
        <Radio.Group
          value={delivery}
          onChange={(event) => {
            setDelivery(event.target.value as Delivery);
          }}
        >
          <Space direction="vertical" size={4}>
            <Radio value="mail">{t("admin.org.invite.deliveryMail")}</Radio>
            <Radio value="password">{t("admin.org.invite.deliveryPassword")}</Radio>
          </Space>
        </Radio.Group>
      </div>
      <RoleCheckboxes
        roles={companyRoles}
        loading={rolesQuery.isPending}
        error={rolesQuery.isError}
        onRetry={() => {
          void rolesQuery.refetch();
        }}
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
        <Alert type="error" showIcon role="alert" message={employeeErrorText(t, failed.error)} />
      ) : null}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Button type="primary" htmlType="submit" block loading={failed.isPending}>
          {delivery === "password"
            ? t("admin.org.invite.submitPassword")
            : t("admin.org.invite.submit")}
        </Button>
        <Button block onClick={onCancel}>
          {t("admin.org.invite.cancel")}
        </Button>
      </div>
      <Consequence items={items} />
    </Form>
  );
}
