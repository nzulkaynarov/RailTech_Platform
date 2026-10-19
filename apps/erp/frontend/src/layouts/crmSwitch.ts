import type { Capabilities } from '@/store/userStore';

/**
 * Кнопка «В CRM» в шапке ERP (FIX-11, CONTRACTS §6): SSO включён на сервере **и** у сотрудника есть
 * сопоставление с пользователем CRM (`capabilities.crm_access`, его создаёт провижининг из CRM).
 * Без сопоставления сервер всё равно ответит 403 `USER_NOT_PROVISIONED` — кнопки нет вовсе.
 */
export function canSwitchToCrm(
  capabilities: Pick<Capabilities, 'sso_enabled' | 'crm_access'> | null | undefined,
): boolean {
  return capabilities?.sso_enabled === true && capabilities.crm_access === true;
}
