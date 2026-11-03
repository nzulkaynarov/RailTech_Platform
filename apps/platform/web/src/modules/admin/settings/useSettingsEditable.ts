import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { settingByKey } from "../settingsRegistry";

/** Можно ли менять страницу Настроек: полный доступ к разделу каталога, которым она открыта (`company.settings` или `admin`). */
export function useSettingsEditable(key: string): boolean {
  const { me } = useAuth();
  const access = settingByKey(key)?.access;
  const resource = access && "resource" in access ? access.resource : "admin";
  return canEdit(me, resource);
}
