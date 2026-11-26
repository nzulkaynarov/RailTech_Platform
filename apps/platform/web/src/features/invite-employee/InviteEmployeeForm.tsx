import { Alert, App, Button, Form, Input, Radio, Select, Space } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { employeeErrorText } from "../../entities/employee/errors";
import { ApiError } from "../../shared/api/errors";
import type { Employee, EmployeeCredentials } from "../../shared/api/generated/model";
import { TemporaryPasswordCard } from "../temporary-password/TemporaryPasswordCard";
import { useCreateEmployeeWithPassword } from "../temporary-password/useTemporaryPassword";
import { useGetDelegationCatalog } from "../../shared/api/generated/platform-bff";
import { useEmployeeInvite } from "../assign-role/useEmployeeMutations";
import { isStepUpError, useStepUp } from "../step-up/useStepUp";

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
  const presetId = useId();
  const catalog = useGetDelegationCatalog();
  const presets = catalog.data?.presets ?? [];
  const [roles, setRoles] = useState<string[]>([]);
  const [rolesTouched, setRolesTouched] = useState(false);
  const [notSent, setNotSent] = useState<{ id: string; crmDown: boolean } | null>(null);
  const [delivery, setDelivery] = useState<Delivery>("mail");
  const deliveryId = useId();
  const [credentials, setCredentials] = useState<EmployeeCredentials | null>(null);
  const stepUp = useStepUp();
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
            // Роль при создании — выдача роли: нужен свежий код второго фактора (ДВ-4б)
            if (
              stepUp.ask(error, () => {
                submit(values);
              })
            )
              return;
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
          if (
            stepUp.ask(error, () => {
              submit(values);
            })
          ) {
            return;
          }
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

  const showRoleNote = rolesTouched && roles.length === 0;
  const failed = delivery === "password" ? create : invite;
  const failure: unknown = failed.error;
  const fieldError =
    failed.isError &&
    !isStepUpError(failure) &&
    !(failure instanceof ApiError && failure.code === "EMAIL_EXISTS") &&
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
    <>
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
          rules={[
            { required: true, whitespace: true, message: t("admin.org.invite.nameRequired") },
          ]}
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
        <div>
          <label htmlFor={presetId} style={{ display: "block", marginBottom: 4 }}>
            {t("admin.org.delegation.preset")}
          </label>
          <Select<string>
            id={presetId}
            style={{ width: "100%" }}
            loading={catalog.isPending}
            status={showRoleNote ? "error" : undefined}
            placeholder={t("admin.org.delegation.presetPlaceholder")}
            value={roles[0]}
            options={presets.map((preset) => ({
              value: preset.id,
              label: `${preset.name} · ${t("admin.org.delegation.presetCount", { count: preset.codes.length })}`,
            }))}
            onChange={(id) => {
              setRoles([id]);
              setRolesTouched(true);
            }}
          />
          {showRoleNote ? (
            <p
              role="alert"
              className="pf-hint"
              style={{ margin: "4px 0 0", color: "var(--rt-color-error, #cf1322)" }}
            >
              {t("admin.org.invite.needRole")}
            </p>
          ) : (
            <p className="pf-hint" style={{ margin: "4px 0 0" }}>
              {t("admin.org.delegation.inviteNote")}
            </p>
          )}
        </div>
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
      </Form>
      {stepUp.dialog}
    </>
  );
}
