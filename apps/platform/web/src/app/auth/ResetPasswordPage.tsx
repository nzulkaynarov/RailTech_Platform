import { Alert, Button, Form, Input } from "antd";
import { useTranslation } from "react-i18next";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { profileErrorText } from "../../features/profile/errors";
import { useResetPassword } from "../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../shared/lib/useDocumentTitle";
import { AuthLayout } from "./AuthLayout";

interface Values {
  next: string;
  confirm: string;
}

/**
 * Новый пароль по ссылке из письма или Telegram (`/reset-password?token=…`, W15-H6). Токен одноразовый; после успеха
 * сессий нет — ведём ко входу. Неверная или просроченная ссылка — словами и «Запросить новую».
 */
export function ResetPasswordPage() {
  const { t } = useTranslation("profile");
  useDocumentTitle(t("reset.title"));
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // Токен — в состояние, а из адреса он уходит сразу: не остаётся в истории браузера, журналах прокси и заголовке Referer.
  const [token] = useState(() => params.get("token") ?? "");
  useEffect(() => {
    if (window.location.search.includes("token=")) {
      window.history.replaceState(window.history.state, "", window.location.pathname);
    }
    // Ни одна страница, на которую уйдёт сотрудник, не должна получить адрес со ссылкой сброса.
    const meta = document.createElement("meta");
    meta.name = "referrer";
    meta.content = "no-referrer";
    document.head.appendChild(meta);
    return () => {
      meta.remove();
    };
  }, []);
  const reset = useResetPassword({
    mutation: {
      gcTime: 0,
      onSuccess: () => {
        void navigate("/login?reset=done", { replace: true });
      },
    },
  });

  if (!token) {
    return (
      <AuthLayout title={t("reset.title")}>
        <Alert type="warning" showIcon role="alert" message={t("reset.noToken")} />
        <div style={{ marginTop: 16 }}>
          <Link to="/forgot-password">{t("reset.requestNew")}</Link>
        </div>
      </AuthLayout>
    );
  }
  const invalid =
    reset.isError &&
    reset.error.code === "VALIDATION_FAILED" &&
    reset.error.details["reason"] === "reset_token_invalid";

  return (
    <AuthLayout title={t("reset.title")} lead={t("reset.lead")}>
      {reset.isError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={profileErrorText(t, "reset", reset.error)}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {invalid ? (
        <Link to="/forgot-password">{t("reset.requestNew")}</Link>
      ) : (
        <Form<Values>
          layout="vertical"
          requiredMark={false}
          onFinish={(values) => {
            reset.mutate({ data: { token, new_password: values.next } });
          }}
        >
          <Form.Item
            name="next"
            label={t("reset.new")}
            rules={[
              { required: true, message: t("reset.newRequired") },
              { min: 10, message: t("reset.tooShort") },
            ]}
          >
            <Input.Password autoComplete="new-password" autoFocus />
          </Form.Item>
          <Form.Item
            name="confirm"
            label={t("reset.confirm")}
            dependencies={["next"]}
            rules={[
              { required: true, message: t("reset.newRequired") },
              ({ getFieldValue }) => ({
                validator: (_rule, value: string | undefined) =>
                  !value || getFieldValue("next") === value
                    ? Promise.resolve()
                    : Promise.reject(new Error(t("reset.mismatch"))),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={reset.isPending}>
            {t("reset.submit")}
          </Button>
        </Form>
      )}
    </AuthLayout>
  );
}
