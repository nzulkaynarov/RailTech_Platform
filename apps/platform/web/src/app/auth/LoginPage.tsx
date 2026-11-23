import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Form, Input, Spin } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";

import {
  getGetMeQueryKey,
  getGetSessionQueryKey,
  useGetSession,
  useGetSetupState,
  useLogin,
  useLoginSecondFactor,
} from "../../shared/api/generated/platform-bff";
import { AuthLayout } from "./AuthLayout";
import { EnrollmentStep } from "./EnrollmentStep";
import { authErrorText } from "./errors";
import { homePath } from "../access";
import type { Me, Session } from "../../shared/api/generated/model";
import { ApiError } from "../../shared/api/errors";
import { safeNext } from "./redirect";

interface LoginValues {
  email: string;
  password: string;
}

interface CodeValues {
  code: string;
  remember: boolean;
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
  // ДВ-4: пароль верен, нужен код второго фактора — `challenge` на 5 минут, сессии ещё нет
  const [challenge, setChallenge] = useState<string | null>(null);
  // ДВ-4б: фактор обязателен по разделам доступа, но не настроен — экран настройки вместо ввода кода
  const [enrolling, setEnrolling] = useState(false);
  const [backup, setBackup] = useState(false);
  const signedIn = (session: Session) => {
    queryClient.setQueryData(getGetSessionQueryKey(), session);
    queryClient.setQueryData(getGetMeQueryKey(), session.me);
    void navigate(session.must_change_password ? "/change-password" : target(session.me), {
      replace: true,
    });
  };
  const login = useLogin({
    mutation: {
      // Пароль не остаётся в кэше мутаций.
      gcTime: 0,
      onSuccess: (result) => {
        if ("second_factor_required" in result) {
          setChallenge(result.challenge);
          setEnrolling(result.enrollment_required === true);
          return;
        }
        signedIn(result);
      },
    },
  });
  const second = useLoginSecondFactor({
    mutation: {
      gcTime: 0,
      onSuccess: signedIn,
      onError: (error) => {
        // время на ввод вышло — снова пароль
        if (error instanceof ApiError && error.code === "SECOND_FACTOR_EXPIRED") setChallenge(null);
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

  if (challenge && enrolling) {
    return (
      <EnrollmentStep
        challenge={challenge}
        onSignedIn={signedIn}
        onRestart={() => {
          setChallenge(null);
          setEnrolling(false);
        }}
      />
    );
  }

  if (challenge) {
    return (
      <AuthLayout
        title={t("login.secondFactor.title")}
        lead={t(backup ? "login.secondFactor.leadBackup" : "login.secondFactor.lead")}
      >
        {second.isError ? (
          <Alert
            type="error"
            showIcon
            role="alert"
            message={authErrorText(t, "login", second.error)}
            style={{ marginBottom: 16 }}
          />
        ) : null}
        <Form<CodeValues>
          layout="vertical"
          requiredMark={false}
          initialValues={{ remember: true }}
          onFinish={(values) => {
            second.mutate({
              data: { challenge, code: values.code.trim(), remember_device: values.remember },
            });
          }}
        >
          <Form.Item
            name="code"
            label={t(backup ? "login.secondFactor.backupCode" : "login.secondFactor.code")}
            rules={[{ required: true, message: t("login.secondFactor.codeRequired") }]}
          >
            <Input
              autoFocus
              autoComplete="one-time-code"
              inputMode={backup ? "text" : "numeric"}
              maxLength={backup ? 9 : 6}
              className="pf-num"
            />
          </Form.Item>
          <Form.Item name="remember" valuePropName="checked">
            <Checkbox>{t("login.secondFactor.remember")}</Checkbox>
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={second.isPending}>
            {t("login.submit")}
          </Button>
          <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between", gap: 8 }}>
            <Button
              type="link"
              style={{ padding: 0 }}
              onClick={() => {
                setBackup((value) => !value);
              }}
            >
              {t(backup ? "login.secondFactor.useApp" : "login.secondFactor.useBackup")}
            </Button>
            <Button
              type="link"
              style={{ padding: 0 }}
              onClick={() => {
                setChallenge(null);
                setBackup(false);
              }}
            >
              {t("login.secondFactor.back")}
            </Button>
          </div>
        </Form>
      </AuthLayout>
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
