/** Доступ к системам ансамбля (FIX-11, M3-CRM-06): `users.platform_access`, истина — на сервере. */
import type { UserUpdate } from "../api/generated/model";

type WithAccess = { platform_access?: readonly string[] | undefined };
type Identity = WithAccess & { sso_enabled?: boolean | undefined };

export const hasErpAccess = (user: WithAccess | null | undefined): boolean =>
  Boolean(user?.platform_access?.includes("erp"));

/**
 * Кнопка перехода в ERP в шапке: SSO включён на сервере **и** админ выдал доступ к ERP.
 * Без доступа кнопки нет вовсе; токен без доступа сервер всё равно не выдаст (403).
 */
export const canSwitchToErp = (identity: Identity | null | undefined): boolean =>
  Boolean(identity?.sso_enabled) && hasErpAccess(identity);

/** Список систем после включения или выключения ERP; CRM есть у всех. */
export function withErpAccess(enabled: boolean): NonNullable<UserUpdate["platform_access"]> {
  return enabled ? ["crm", "erp"] : ["crm"];
}
