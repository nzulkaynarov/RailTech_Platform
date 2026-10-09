import type { AccessControlProvider } from "@refinedev/core";
import type { QueryClient } from "@tanstack/react-query";

import { me, permissions } from "../../api/generated/crm";
import { unwrap } from "../../api/http";
import type { PermissionsResponse } from "../../api/generated/model";
import { keys } from "../../api/queries";

/**
 * Права приходят с бэка (`GET /me/permissions`); фронт только скрывает и блокирует UI.
 * Истина — проверка на каждом эндпоинте (SPEC §10.3).
 */
// Ресурс Refine → (ресурс, действие) матрицы прав бэкенда.
const RESOURCE_MAP: Record<string, [string, string]> = {
  inbox: ["leads", "take"], // очередь работы — не наблюдателю (SPEC §10.1)
  leads: ["leads", "read"],
  dashboard: ["dashboard", "read"],
  clients: ["clients", "read"],
  kb: ["kb", "read"],
  gaps: ["kb", "read"],
  settings: ["settings", "read"],
  audit: ["audit", "read"],
  users: ["users", "read"],
  profile: ["self", "read"],
};
const ADMIN_SECTIONS = new Set(["kb", "gaps", "settings", "audit", "users"]);

export function accessControlProvider(client: QueryClient): AccessControlProvider {
  return {
    can: async ({ resource, action }) => {
      const [target, verb] = RESOURCE_MAP[resource ?? ""] ?? [resource ?? "", action];
      if (target === "self") return { can: true };
      const matrix = await client.query<PermissionsResponse>({
        queryKey: keys.permissions,
        queryFn: async () => unwrap(await permissions()),
        staleTime: 60_000,
      });
      if (ADMIN_SECTIONS.has(resource ?? "")) {
        // Режим «Менеджер» скрывает админские разделы — только навигация (SPEC §10.2).
        const user = await client.query({
          queryKey: keys.me,
          queryFn: async () => unwrap(await me()),
          staleTime: 60_000,
        });
        if (user.ui_mode !== "admin") return { can: false };
      }
      return { can: Boolean(matrix.permissions[target]?.[verb]) };
    },
    options: { buttons: { enableAccessControl: true, hideIfUnauthorized: true } },
  };
}

/** (ресурс, действие) матрицы прав для раздела Refine — без учёта режима «Менеджер». */
export function sectionPermission(resource: string): [string, string] | null {
  return RESOURCE_MAP[resource] ?? null;
}

export function allowed(
  matrix: PermissionsResponse | undefined,
  resource: string,
  action: string,
): boolean {
  return Boolean(matrix?.permissions[resource]?.[action]);
}
