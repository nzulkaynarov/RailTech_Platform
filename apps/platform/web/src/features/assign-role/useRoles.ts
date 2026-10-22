import { useListRoles } from "../../shared/api/generated/platform-bff";

/** Роли Платформы из `GET /admin/roles` (ADR-0012): администратор создаёт их сам, названия — данные. */
export function useRoles() {
  const query = useListRoles();
  return { query, roles: query.data?.items ?? [] };
}
