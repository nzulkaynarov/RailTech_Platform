import type { ReactNode } from "react";

import type { AccessRule } from "../modules/types";
import { Forbidden } from "../shared/ui/Forbidden";
import { canSee } from "./access";
import { useAuth } from "./auth/useAuth";

/**
 * Страж раздела по `Me.resources` (матрица `platform-rbac.yaml`, объединение ролей): нет доступа — `Forbidden`
 * по прямому URL (SPEC-v3 §11.2 п. 7). Скрытые разделы в рейле и подменю не рендерятся вовсе — это решает AppShell.
 */
export function RequireAccess({ rule, children }: { rule: AccessRule; children: ReactNode }) {
  const { me } = useAuth();
  return canSee(me, rule) ? children : <Forbidden activeRole={me.active_role != null} />;
}
