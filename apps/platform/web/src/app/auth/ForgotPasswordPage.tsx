import { Alert, Button, Form, Input } from "antd";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { profileErrorText } from "../../features/profile/errors";
import { useForgotPassword } from "../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../shared/lib/useDocumentTitle";
import { AuthLayout } from "./AuthLayout";

interface Values {
  identifier: string;
}

/**
 * «Забыли пароль?» (W15-H6): почта → ссылка сброса на почту или в Telegram; нет ни того, ни другого — к администратору.
 * Ответ после отправки один и тот же для любой учётной записи, поэтому экран не говорит, найден ли адрес.
 */
export function ForgotPasswordPage() {
  const { t } = useTranslation("profile");
  useDocumentTitle(t("forgot.title"));
  const forgot = useForgotPassword({ mutation: { gcTime: 0 } });

  return (
    <AuthLayout title={t("forgot.title")} lead={t("forgot.lead")}>
      {forgot.isSuccess ? (
        <Alert
          type="success"
          showIcon
          role="status"
          message={t("forgot.sentTitle")}
          description={t("forgot.sent")}
          style={{ marginBottom: 16 }}
        />
      ) : (
        <>
          {forgot.isError ? (
            <Alert
              type="error"
              showIcon
              role="alert"
              message={profileErrorText(t, "forgot", forgot.error)}
              style={{ marginBottom: 16 }}
            />
          ) : null}
          <Form<Values>
            layout="vertical"
            requiredMark={false}
            onFinish={(values) => {
              forgot.mutate({ data: { identifier: values.identifier.trim() } });
            }}
          >
            <Form.Item
              name="identifier"
              label={t("forgot.email")}
              rules={[
                { required: true, whitespace: true, message: t("forgot.emailRequired") },
                { type: "email", message: t("forgot.emailInvalid") },
              ]}
            >
              <Input type="email" autoComplete="username" inputMode="email" autoFocus />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={forgot.isPending}>
              {t("forgot.submit")}
            </Button>
          </Form>
        </>
      )}
      <div style={{ marginTop: 16 }}>
        <Link to="/login">{t("forgot.back")}</Link>
      </div>
    </AuthLayout>
  );
}
