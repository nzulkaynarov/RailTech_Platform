import { canEdit } from "../../../app/access";
import type { Me, PersonRef } from "../../../shared/api/generated/model";

/**
 * «Создать заявку» из лида: право на клиентов (`crm.clients: full`) и лид свободен или ведёт сам сотрудник — чужого лида CRM
 * не отдаст (403 `not_lead_owner`); администратор может всё. Кнопки нет, чтобы не заполнять форму впустую.
 */
export function canCreateFromLead(me: Me, assigned: PersonRef | null): boolean {
  if (!canEdit(me, "crm.clients")) return false;
  return assigned === null || assigned.id === me.id || canEdit(me, "admin");
}
