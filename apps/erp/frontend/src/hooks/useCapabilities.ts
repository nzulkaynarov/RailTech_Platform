import { useUserStore } from '@/store/userStore';

/**
 * Право бэк-офиса из /me (`capabilities.permissions`, M1-ERP-05): объединение ролей сотрудника,
 * у администратора (is_superuser) — весь каталог. Нет права — кнопка прячется или блокируется;
 * пустой список = прав нет (роль «Наблюдатель»), без обхода по должности OWNER. Это только UX —
 * истину держит сервер (гейт эндпоинтов и сервисы проверяют те же коды).
 */
export function useHasCompanyPermission(permission: string): boolean {
  return useUserStore((s) => s.capabilities.permissions.includes(permission));
}

/**
 * Wave B2 (auto-claim) — true, когда в команде один сотрудник с правом `deal.manage`: «Взять в
 * работу» тогда шум (распределять заявки не между кем). Только скрытие кнопки; распределение
 * решает сервер. Флаг /me — `capabilities.is_solo_team` (до M1-ERP-05 — `is_solo_seller`).
 */
export function useIsSoloTeam(): boolean {
  return useUserStore((s) => s.capabilities?.is_solo_team === true);
}
