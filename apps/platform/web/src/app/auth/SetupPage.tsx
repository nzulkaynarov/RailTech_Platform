import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Form, Input, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate } from "react-router";

import { WIZARD_PATH } from "../../entities/setup/steps";
import {
  getGetMeQueryKey,
  getGetSessionQueryKey,
  useCreateFirstAdmin,
  useGetSession,
  useGetSetupState,
} from "../../shared/api/generated/platform-bff";
import { lines } from "../../features/first-run/lines";
import { useDocumentTitle } from "../../shared/lib/useDocumentTitle";
import { Consequence } from "../../shared/ui/Consequence";
import { LinkButton } from "../../shared/ui/LinkButton";
import { homePath } from "../access";
import { AuthLayout } from "./AuthLayout";
import { authErrorText } from "./errors";

interface SetupValues {
  code: string;
  name: string;
  email: string;
  password: string;
  confirm: string;
}

const MIN_PASSWORD = 10;

/**
 * «Первый запуск» до входа (SPEC-v3 §7.6, W13-A4): пока в CRM нет администратора, вместо входа открывается этот экран.
 * Код первого запуска выдаёт тот, кто разворачивал Платформу (сервер пишет его в журнал `crm-api` — об этом в свёрнутом блоке
 * «Подробнее для техспециалиста»); по коду, имени, почте и паролю BFF создаёт администратора в CRM
 * и открывает его сессию — дальше мастер в Admin (`/admin/setup`). Когда администратор уже есть, экран отправляет ко входу.
 */
export function SetupPage() {
  const { t } = useTranslation("shell");
  useDocumentTitle(t("setup.title"));
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const state = useGetSetupState({ query: { retry: false } });
  const existing = useGetSession({ query: { retry: false } });
  const create = useCreateFirstAdmin({
    mutation: {
      // Пароль администратора не остаётся в кэше мутаций.
      gcTime: 0,
      onSuccess: (session) => {
        queryClient.setQueryData(getGetSessionQueryKey(), session);
        queryClient.setQueryData(getGetMeQueryKey(), session.me);
        void navigate(WIZARD_PATH, { replace: true });
      },
    },
  });

  const spinner = (
    <div
      role="status"
      aria-label={t("setup.checking")}
      style={{ minHeight: "100dvh", display: "grid", placeItems: "center" }}
    >
      <Spin size="large" />
    </div>
  );
  if (existing.isPending || state.isPending) return spinner;
  // Сессия появилась после создания администратора: в мастер ведёт `onSuccess`, не «домой».
  if (existing.isSuccess && !create.isSuccess) {
    return (
      <Navigate
        to={existing.data.must_change_password ? "/change-password" : homePath(existing.data.me)}
        replace
      />
    );
  }
  if (state.isError) {
    return (
      <AuthLayout title={t("setup.stateErrorTitle")} lead={t("setup.stateErrorText")}>
        <Button
          type="primary"
          block
          onClick={() => {
            void state.refetch();
          }}
        >
          {t("setup.retry")}
        </Button>
      </AuthLayout>
    );
  }
  // Администратор уже создан (в том числе только что — сессия ещё открывается): экран больше не нужен.
  if (!state.data.needs_admin && !create.isPending && !create.isSuccess) {
    return (
      <AuthLayout title={t("setup.doneTitle")} lead={t("setup.doneText")}>
        <LinkButton type="primary" block to="/login">
          {t("setup.doneAction")}
        </LinkButton>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={t("setup.title")} lead={t("setup.lead")}>
      {create.isError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={authErrorText(t, "setup", create.error)}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      <Form<SetupValues>
        layout="vertical"
        requiredMark={false}
        onFinish={(values) => {
          create.mutate({
            data: {
              code: values.code.trim(),
              name: values.name.trim(),
              email: values.email.trim(),
              password: values.password,
            },
          });
        }}
      >
        <Form.Item
          name="code"
          label={t("setup.code")}
          extra={
            <>
              {t("setup.codeHelp")}
              <details style={{ marginTop: 4 }}>
                <summary style={{ cursor: "pointer" }}>{t("setup.codeTechSummary")}</summary>
                {t("setup.codeTechText")}
              </details>
            </>
          }
          rules={[{ required: true, whitespace: true, message: t("setup.codeRequired") }]}
        >
          <Input autoComplete="off" spellCheck={false} autoFocus />
        </Form.Item>
        <Form.Item
          name="name"
          label={t("setup.name")}
          rules={[{ required: true, whitespace: true, message: t("setup.nameRequired") }]}
        >
          <Input autoComplete="name" maxLength={120} />
        </Form.Item>
        <Form.Item
          name="email"
          label={t("setup.email")}
          rules={[
            { required: true, whitespace: true, message: t("setup.emailRequired") },
            { type: "email", message: t("setup.emailInvalid") },
          ]}
        >
          <Input type="email" autoComplete="username" inputMode="email" maxLength={254} />
        </Form.Item>
        <Form.Item
          name="password"
          label={t("setup.password")}
          extra={t("setup.passwordHint")}
          rules={[
            { required: true, message: t("setup.passwordRequired") },
            { min: MIN_PASSWORD, message: t("setup.passwordTooShort") },
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm"
          label={t("setup.confirm")}
          dependencies={["password"]}
          rules={[
            { required: true, message: t("setup.passwordRequired") },
            ({ getFieldValue }) => ({
              validator: (_rule, value: string | undefined) =>
                !value || getFieldValue("password") === value
                  ? Promise.resolve()
                  : Promise.reject(new Error(t("setup.mismatch"))),
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <div style={{ marginBottom: 16 }}>
          <Consequence items={lines(t, "setup.consequence")} />
        </div>
        <Button type="primary" htmlType="submit" block loading={create.isPending}>
          {t("setup.submit")}
        </Button>
      </Form>
    </AuthLayout>
  );
}
