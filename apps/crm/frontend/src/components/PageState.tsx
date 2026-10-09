import { Button, Card, Result } from "antd";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "../api/http";
import { t } from "../i18n/ru";

type Query = { isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown };

/** Экран вместо содержимого: 403, 404 или ошибка с «Повторить» (аудит UI U-02). */
export function QueryError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const navigate = useNavigate();
  const status = error instanceof ApiError ? error.status : 0;
  const home = (
    <Button
      key="home"
      onClick={() => {
        void navigate("/");
      }}
    >
      {t.state.home}
    </Button>
  );
  if (status === 403) {
    return (
      <Result
        status="403"
        title={t.state.forbidden}
        subTitle={t.state.forbiddenHint}
        extra={home}
      />
    );
  }
  if (status === 404) {
    return (
      <Result status="404" title={t.state.notFound} subTitle={t.state.notFoundHint} extra={home} />
    );
  }
  return (
    <Result
      status="error"
      title={t.state.error}
      subTitle={error instanceof Error ? error.message : undefined}
      extra={
        onRetry ? (
          <Button type="primary" onClick={onRetry}>
            {t.state.retry}
          </Button>
        ) : (
          home
        )
      }
    />
  );
}

/**
 * Обёртка страницы над запросом: ошибка → экран ошибки; загрузка → скелетон
 * (`inline` — показать содержимое сразу, например таблицу со своим спиннером).
 */
export function PageState({
  query,
  ready = true,
  inline = false,
  children,
}: {
  query: Query;
  ready?: boolean;
  inline?: boolean;
  children: ReactNode;
}) {
  if (query.isError) {
    return (
      <QueryError
        error={query.error}
        onRetry={() => {
          void query.refetch();
        }}
      />
    );
  }
  if (!inline && (query.isLoading || !ready)) return <Card loading />;
  return <>{children}</>;
}
