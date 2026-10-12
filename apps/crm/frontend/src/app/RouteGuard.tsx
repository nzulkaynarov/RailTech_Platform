import { Alert, Button, Card } from "antd";
import type { ReactNode } from "react";
import { Navigate } from "react-router";

import { ApiError } from "../api/http";
import { useMe, usePermissionsQuery } from "../api/queries";
import { useSetUiMode } from "../hooks/useSetUiMode";
import { QueryError } from "../components/PageState";
import { t } from "../i18n/ru";
import { homePath } from "./navigation";
import { allowed, isAdminSection, sectionPermission } from "./providers/access";

/** Разделы, куда без права не «запрещаем», а ведём на свою стартовую страницу. */
const REDIRECT_IF_FORBIDDEN = new Set(["inbox"]);

/** Админ в режиме «Менеджер» открыл админский раздел: подсказка и возврат одним нажатием. */
function ManagerModeBanner() {
  const setMode = useSetUiMode();
  return (
    <Alert
      type="info"
      showIcon
      className="mode-banner"
      message={t.managerMode.banner}
      action={
        <Button
          size="small"
          type="primary"
          onClick={() => {
            setMode("admin");
          }}
        >
          {t.managerMode.back}
        </Button>
      }
    />
  );
}

/**
 * Раздел по прямому URL без прав — экран 403 вместо пустой таблицы (аудит UI U-02);
 * очередь «Входящие» без права — переход на стартовую страницу роли (наблюдатель → дашборд).
 * Проверяются права, а не режим «Админ/Менеджер»: режим — только навигация (SPEC §10.2),
 * поэтому в режиме «Менеджер» админский раздел открывается, но с баннером.
 */
export function RouteGuard({ resource, children }: { resource: string; children: ReactNode }) {
  const perms = usePermissionsQuery();
  const me = useMe();
  const target = sectionPermission(resource);
  if (!target) return <>{children}</>;
  if (perms.isLoading) return <Card loading />;
  if (!allowed(perms.data, target[0], target[1])) {
    if (REDIRECT_IF_FORBIDDEN.has(resource)) {
      return <Navigate to={homePath(perms.data)} replace />;
    }
    return <QueryError error={new ApiError(403, "forbidden", "")} />;
  }
  const managerMode = me.data?.roles.includes("admin") && me.data.ui_mode !== "admin";
  if (managerMode && isAdminSection(resource)) {
    return (
      <>
        <ManagerModeBanner />
        {children}
      </>
    );
  }
  return <>{children}</>;
}

/** Несуществующий адрес: свой текст — «запись удалена» здесь неправда (отчёт 2). */
export const NotFound = () => (
  <QueryError
    error={new ApiError(404, "not_found", "")}
    notFound={{ title: t.state.pageNotFound, hint: t.state.pageNotFoundHint }}
  />
);
