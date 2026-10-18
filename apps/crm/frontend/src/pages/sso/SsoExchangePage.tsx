import { useInvalidateAuthStore } from "@refinedev/core";
import { Alert, Button, Card, Spin, Typography } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { ssoExchange } from "../../api/generated/crm";
import { ApiError, tokenStore } from "../../api/http";
import { errorText, t } from "../../i18n/ru";
import "../pages.css";

/**
 * Страница приёма и обмена платформенного SSO-токена из ERP (CONTRACTS §6, M3-CRM-06).
 * Извлекает JWT из URL hash фрагмента `#token=<jwt>`, обменивает на сессию CRM и перенаправляет.
 */
export function SsoExchangePage() {
  const navigate = useNavigate();
  const invalidateAuth = useInvalidateAuthStore();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function processSso() {
      const hash = window.location.hash.replace(/^#/, "");
      const params = new URLSearchParams(hash);
      const token = params.get("token") || (hash.startsWith("token=") ? hash.slice(6) : null);

      if (!token) {
        if (active) {
          setError(t.sso.missingToken);
          setLoading(false);
        }
        return;
      }

      try {
        const data = await ssoExchange({ token });
        if (!active) return;
        tokenStore.set(data.access_token);

        // Удаляем токен из URL, чтобы он не оседал в истории
        window.history.replaceState(null, "", "/");

        // Обновляем состояние авторизации Refine
        await invalidateAuth();

        void navigate("/", { replace: true });
      } catch (err) {
        if (!active) return;
        setError(errorText(err instanceof ApiError ? err.code : undefined, t.sso.exchangeFailed));
        setLoading(false);
      }
    }

    void processSso();

    return () => {
      active = false;
    };
  }, [invalidateAuth, navigate]);

  return (
    <main className="page-center">
      <Card className="auth-card" style={{ textAlign: "center" }}>
        <Typography.Text type="secondary">{t.app.title}</Typography.Text>
        <Typography.Title level={2} className="page-title auth-title" style={{ marginTop: 8 }}>
          {t.sso.title}
        </Typography.Title>

        {loading ? (
          <div style={{ padding: "32px 0" }}>
            <Spin size="large" />
            <Typography.Paragraph type="secondary" style={{ marginTop: 16 }}>
              {t.sso.syncing}
            </Typography.Paragraph>
          </div>
        ) : null}

        {error ? (
          <div style={{ marginTop: 16 }}>
            <Alert
              type="error"
              showIcon
              message={t.sso.errorTitle}
              description={error}
              style={{ textAlign: "left", marginBottom: 20 }}
            />
            <Button type="primary" block onClick={() => void navigate("/login")}>
              {t.sso.loginWithPassword}
            </Button>
          </div>
        ) : null}
      </Card>
    </main>
  );
}
