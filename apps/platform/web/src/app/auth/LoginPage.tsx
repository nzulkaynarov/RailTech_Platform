import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Form, Input, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import {
  getGetMeQueryKey,
  getGetSessionQueryKey,
  useGetSession,
  useLogin,
} from "../../shared/api/generated/platform-bff";
import { AuthLayout } from "./AuthLayout";
import { authErrorText } from "./errors";
import { safeNext } from "./redirect";

interface LoginValues {
  email: string;
  password: string;
}

/** Страница «Вход»: почта и пароль CRM (SPEC-v3 §6, 02-architecture.md §3). Ошибки — по `Error.code`. */
export function LoginPage() {
  const { t } = useTranslation("shell");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const existing = useGetSession({ query: { retry: false } });
  const login = useLogin({
    mutation: {
      onSuccess: (session) => {
        queryClient.setQueryData(getGetSessionQueryKey(), session);
        queryClient.setQueryData(getGetMeQueryKey(), session.me);
        void navigate(session.must_change_password ? "/change-password" : next, { replace: true });
      },
    },
  });

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
    return <Navigate to={existing.data.must_change_password ? "/change-password" : next} replace />;
  }

  return (
    <AuthLayout title={t("login.title")} lead={t("login.lead")}>
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
      </Form>
    </AuthLayout>
  );
}
