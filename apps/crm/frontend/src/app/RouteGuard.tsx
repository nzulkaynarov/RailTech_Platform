import { Card } from "antd";
import type { ReactNode } from "react";

import { ApiError } from "../api/http";
import { usePermissionsQuery } from "../api/queries";
import { QueryError } from "../components/PageState";
import { t } from "../i18n/ru";
import { allowed, sectionPermission } from "./providers/access";

/**
 * Раздел по прямому URL без прав — экран 403 вместо пустой таблицы (аудит UI U-02).
 * Проверяются права, а не режим «Админ/Менеджер»: режим — только навигация (SPEC §10.2).
 */
export function RouteGuard({ resource, children }: { resource: string; children: ReactNode }) {
  const perms = usePermissionsQuery();
  const target = sectionPermission(resource);
  if (!target) return <>{children}</>;
  if (perms.isLoading) return <Card loading />;
  if (!allowed(perms.data, target[0], target[1])) {
    return <QueryError error={new ApiError(403, "forbidden", "")} />;
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
