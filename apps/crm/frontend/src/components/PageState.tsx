import { Alert, Button, Card, Result, Skeleton } from "antd";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "../api/http";
import { t } from "../i18n/ru";
import { EmptyState, type EmptyStateProps } from "./EmptyState";

type Query = { isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown };

/** Заголовок экрана-состояния — h1: на этих экранах нет `PageHeader` (WCAG 1.3.1). */
const heading = (text: string) => <h1 className="result-heading">{text}</h1>;

/**
 * Экран вместо содержимого: 403, 404 или ошибка с «Повторить» (аудит UI U-02).
 * `notFound` — свои тексты 404 (например, для неверного адреса вместо «запись удалена»).
 */
export function QueryError({
  error,
  onRetry,
  notFound,
}: {
  error: unknown;
  onRetry?: () => void;
  notFound?: { title: string; hint: string };
}) {
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
        title={heading(t.state.forbidden)}
        subTitle={t.state.forbiddenHint}
        extra={home}
      />
    );
  }
  if (status === 404) {
    const texts = notFound ?? { title: t.state.notFound, hint: t.state.notFoundHint };
    return <Result status="404" title={heading(texts.title)} subTitle={texts.hint} extra={home} />;
  }
  return (
    <Result
      status="error"
      title={heading(t.state.error)}
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

/** Ошибка вторичного блока (заметки, документы, решения): компактно, с «Повторить». */
export function SectionError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <Alert
      type="error"
      showIcon
      message={t.state.error}
      description={error instanceof Error ? error.message : undefined}
      action={
        <Button size="small" onClick={onRetry}>
          {t.state.retry}
        </Button>
      }
    />
  );
}

type PageStateProps = {
  query: Query;
  ready?: boolean;
  /** Показать содержимое сразу, без скелетона (например, таблицу со своим спиннером). */
  inline?: boolean;
  /** `section` — для вторичного запроса внутри страницы: компактная ошибка и скелетон. */
  variant?: "page" | "section";
  /** Пустое состояние вместо содержимого: `empty={!items.length && { title, hint }}`. */
  empty?: EmptyStateProps | false | null;
  children: ReactNode;
};

/**
 * Обёртка над запросом: ошибка → экран ошибки (или `SectionError`); загрузка → скелетон;
 * пусто → `EmptyState`. Вторичные запросы тоже оборачиваются, чтобы ошибка не выглядела
 * как «данных нет».
 */
export function PageState({
  query,
  ready = true,
  inline = false,
  variant = "page",
  empty,
  children,
}: PageStateProps) {
  const retry = () => {
    void query.refetch();
  };
  if (query.isError) {
    return variant === "section" ? (
      <SectionError error={query.error} onRetry={retry} />
    ) : (
      <QueryError error={query.error} onRetry={retry} />
    );
  }
  if (!inline && (query.isLoading || !ready)) {
    return variant === "section" ? <Skeleton active /> : <Card loading />;
  }
  if (empty) return <EmptyState {...empty} />;
  return <>{children}</>;
}
