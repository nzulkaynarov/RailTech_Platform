import { useQueryClient } from "@tanstack/react-query";
import { Button, Result, Spin } from "antd";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router";

import { ApiError } from "../../shared/api/errors";
import { useGetMe, useGetSession } from "../../shared/api/generated/platform-bff";
import { onSessionExpired } from "../../shared/api/http";
import { rememberLanguage } from "../../shared/i18n";
import i18n from "../../shared/i18n";
import { loginPath } from "./redirect";
import { AuthContext } from "./useAuth";

function isSessionExpired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

function FullPageSpin({ label }: { label: string }) {
  return (
    <div
      role="status"
      aria-label={label}
      style={{ minHeight: "100dvh", display: "grid", placeItems: "center" }}
    >
      <Spin size="large" />
    </div>
  );
}

/**
 * Страж маршрутов после входа: сессия и профиль (`GET /auth/session`, `GET /me`). Нет сессии — экран входа с возвратом на
 * тот же адрес; обязательная смена пароля — только страница смены; 401 `SESSION_EXPIRED` в любом запросе — то же, что нет сессии.
 */
export function AuthGate() {
  const { t } = useTranslation("shell");
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const session = useGetSession();
  const meQuery = useGetMe();

  const here = useRef(location.pathname + location.search);
  useEffect(() => {
    here.current = location.pathname + location.search;
  });
  useEffect(
    () =>
      onSessionExpired(() => {
        queryClient.clear();
        void navigate(loginPath(here.current), { replace: true });
      }),
    [navigate, queryClient],
  );

  const me = meQuery.data;
  const mustChangePassword = session.data?.must_change_password ?? false;
  const language = me?.language;
  useEffect(() => {
    if (language && language !== i18n.language) void i18n.changeLanguage(language);
    if (language) rememberLanguage(language);
  }, [language]);

  const value = useMemo(() => (me ? { me, mustChangePassword } : null), [me, mustChangePassword]);

  if (isSessionExpired(session.error) || isSessionExpired(meQuery.error)) {
    return <Navigate to={loginPath(location.pathname + location.search)} replace />;
  }
  if (session.isError || meQuery.isError) {
    return (
      <Result
        status="error"
        title={t("session.errorTitle")}
        subTitle={t("session.errorText")}
        extra={
          <Button
            type="primary"
            onClick={() => {
              void session.refetch();
              void meQuery.refetch();
            }}
          >
            {t("session.retry")}
          </Button>
        }
      />
    );
  }
  if (!value) return <FullPageSpin label={t("loading")} />;
  if (value.mustChangePassword && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  return (
    <AuthContext.Provider value={value}>
      <Outlet />
    </AuthContext.Provider>
  );
}
