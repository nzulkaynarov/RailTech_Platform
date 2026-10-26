import { useInvalidateAuthStore } from "@refinedev/core";
import { Alert, Button, Card, Form, Input, Typography } from "antd";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import { keys } from "../../api/queries";
import { useSetupState } from "../../api/systemQueries";

import { authProvider } from "../../app/providers/auth";
import { t } from "../../i18n/ru";
import { safeNextPath, withNext } from "../../lib/nextPath";
import "../pages.css";

type Values = { email: string; password: string };

/**
 * Вход. Навигация — только после обновления auth-кэша Refine: иначе защищённый
 * маршрут успевает увидеть устаревший `check = false` и вернуть на /login.
 */
export function LoginPage() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [params] = useSearchParams();
  const invalidateAuth = useInvalidateAuthStore();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const setup = useSetupState();

  const submit = async (values: Values) => {
    setPending(true);
    setError(null);
    const result = await authProvider.login(values);
    if (!result.success) {
      setError(result.error?.message ?? t.auth.invalid);
      setPending(false);
      return;
    }
    // Права и профиль прошлого пользователя того же окна не должны решать, куда вести нового.
    client.removeQueries({ queryKey: keys.permissions });
    client.removeQueries({ queryKey: keys.me });
    await invalidateAuth();
    setPending(false);
    // Адрес, с которого выбросило на вход (`?to=`), сохраняется; иначе «/» — первый доступный раздел.
    void navigate(withNext(result.redirectTo ?? "/", safeNextPath(params.get("to"))));
  };

  // Первый запуск: администратора ещё нет — вместо входа мастер настройки.
  if (setup.data?.needs_setup) return <Navigate to="/setup" replace />;
  return (
    <main className="page-center">
      <Card className="auth-card">
        <Typography.Text type="secondary">{t.app.title}</Typography.Text>
        <Typography.Title level={1} className="page-title auth-title">
          {t.auth.title}
        </Typography.Title>
        {error ? <Alert type="error" showIcon message={error} className="auth-alert" /> : null}
        <Form<Values> layout="vertical" onFinish={(values) => void submit(values)}>
          <Form.Item name="email" label={t.auth.email} rules={[{ required: true, type: "email" }]}>
            <Input autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item name="password" label={t.auth.password} rules={[{ required: true }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={pending}>
            {t.auth.submit}
          </Button>
        </Form>
      </Card>
    </main>
  );
}
