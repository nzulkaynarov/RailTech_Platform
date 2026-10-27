import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Form, Input, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";

import {
  getGetMeQueryKey,
  getGetSessionQueryKey,
  useGetSession,
  useGetSetupState,
  useLogin,
} from "../../shared/api/generated/platform-bff";
import { AuthLayout } from "./AuthLayout";
import { authErrorText } from "./errors";
import { homePath } from "../access";
import type { Me } from "../../shared/api/generated/model";
import { safeNext } from "./redirect";

interface LoginValues {
  email: string;
  password: string;
}

/** Страница «Вход»: почта и пароль CRM (SPEC-v3 §6, docs/architecture/platform-bff.md §3). Ошибки — по `Error.code`. */
export function LoginPage() {
  const { t } = useTranslation("shell");
  const { t: tProfile } = useTranslation("profile");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const asked = params.get("next");
  const next = safeNext(asked);
  // Без явного адреса возврата — «домой» по ролям: у роли без Dashboard это её первый раздел.
  const target = (me: Me) => (asked ? next : homePath(me));
  const expired = params.get("reason") === "expired";
  // Пароль только что сменён по ссылке из письма (`/reset-password`): подсказываем войти с новым.
  const resetDone = params.get("reset") === "done";
  const existing = useGetSession({ query: { retry: false } });
  // Администратора ещё нет — вместо входа «Первый запуск» (W13-A4). Сбой запроса вход не блокирует.
  const setupState = useGetSetupState({ query: { retry: false } });
  const login = useLogin({
    mutation: {
      // Пароль не остаётся в кэше мутаций.
      gcTime: 0,
      onSuccess: (session) => {
        queryClient.setQueryData(getGetSessionQueryKey(), session);
        queryClient.setQueryData(getGetMeQueryKey(), session.me);
        void navigate(session.must_change_password ? "/change-password" : target(session.me), {
          replace: true,
        });
      },
    },
  });

  if (setupState.data?.needs_admin && !existing.isSuccess) {
    return <Navigate to="/setup" replace />;
  }
  if (existing.isPending) {
    return (
      <div
        role="status"
        aria-label={t("loading")}
        style={{ minHeight: "100dvh", display: "grid", placeItems: "center" }}
      >
        <Spin size="large" />
      </div>
    );
  }
  if (existing.isSuccess) {
    return (
      <Navigate
        to={existing.data.must_change_password ? "/change-password" : target(existing.data.me)}
        replace
      />
    );
  }

  return (
    <AuthLayout title={t("login.title")} lead={t("login.lead")}>
      {expired && !login.isError ? (
        <Alert
          type="info"
          showIcon
          role="status"
          message={t("login.expired")}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {resetDone && !login.isError ? (
        <Alert
          type="success"
          showIcon
          role="status"
          message={tProfile("reset.done")}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {login.isError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={authErrorText(t, "login", login.error)}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      <Form<LoginValues>
        layout="vertical"
        requiredMark={false}
        onFinish={(values) => {
          login.mutate({ data: { email: values.email.trim(), password: values.password } });
        }}
      >
        <Form.Item
          name="email"
          label={t("login.email")}
          rules={[
            { required: true, message: t("login.emailRequired") },
            { type: "email", message: t("login.emailInvalid") },
          ]}
        >
          <Input type="email" autoComplete="username" inputMode="email" autoFocus />
        </Form.Item>
        <Form.Item
          name="password"
          label={t("login.password")}
          rules={[{ required: true, message: t("login.passwordRequired") }]}
        >
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" block loading={login.isPending}>
          {t("login.submit")}
        </Button>
        <div style={{ marginTop: 12, textAlign: "center" }}>
          <Link to="/forgot-password">{tProfile("forgot.link")}</Link>
        </div>
      </Form>
    </AuthLayout>
  );
}
