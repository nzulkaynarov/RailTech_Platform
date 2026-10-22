import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import {
  getGetSessionQueryKey,
  useChangePassword,
  useLogout,
} from "../../shared/api/generated/platform-bff";
import { AuthLayout } from "./AuthLayout";
import { useAuth } from "./useAuth";
import { authErrorText } from "./errors";
import { homePath } from "../access";

interface PasswordValues {
  current: string;
  next: string;
  confirm: string;
}

/**
 * Смена пароля. При `Session.must_change_password` — единственная доступная страница (остальные ведут сюда),
 * без «Отмена»; из меню аватара — добровольная смена.
 */
export function ChangePasswordPage() {
  const { t } = useTranslation("shell");
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { mustChangePassword, me } = useAuth();
  const home = homePath(me);
  const logout = useLogout({
    mutation: {
      onSettled: () => {
        queryClient.clear();
        void navigate("/login", { replace: true });
      },
    },
  });
  const change = useChangePassword({
    mutation: {
      onSuccess: async () => {
        message.success(t("changePassword.done"));
        await queryClient.invalidateQueries({ queryKey: getGetSessionQueryKey() });
        void navigate(home, { replace: true });
      },
    },
  });

  return (
    <AuthLayout
      title={t("changePassword.title")}
      lead={mustChangePassword ? t("changePassword.leadForced") : t("changePassword.lead")}
    >
      {change.isError ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={authErrorText(t, "changePassword", change.error)}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      <Form<PasswordValues>
        layout="vertical"
        requiredMark={false}
        onFinish={(values) => {
          change.mutate({ data: { current_password: values.current, new_password: values.next } });
        }}
      >
        <Form.Item
          name="current"
          label={t("changePassword.current")}
          rules={[{ required: true, message: t("changePassword.currentRequired") }]}
        >
          <Input.Password autoComplete="current-password" autoFocus />
        </Form.Item>
        <Form.Item
          name="next"
          label={t("changePassword.new")}
          extra={t("changePassword.newHint")}
          rules={[
            { required: true, message: t("changePassword.newRequired") },
            { min: 8, message: t("changePassword.newTooShort") },
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm"
          label={t("changePassword.confirm")}
          dependencies={["next"]}
          rules={[
            { required: true, message: t("changePassword.newRequired") },
            ({ getFieldValue }) => ({
              validator: (_rule, value: string | undefined) =>
                !value || getFieldValue("next") === value
                  ? Promise.resolve()
                  : Promise.reject(new Error(t("changePassword.mismatch"))),
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" block loading={change.isPending}>
          {t("changePassword.submit")}
        </Button>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 12 }}>
          {mustChangePassword ? null : (
            <Button
              type="link"
              style={{ padding: 0 }}
              onClick={() => {
                void navigate(home);
              }}
            >
              {t("changePassword.cancel")}
            </Button>
          )}
          <Button
            type="link"
            style={{ padding: 0, marginLeft: "auto" }}
            onClick={() => {
              logout.mutate();
            }}
          >
            {t("changePassword.logout")}
          </Button>
        </div>
      </Form>
    </AuthLayout>
  );
}
