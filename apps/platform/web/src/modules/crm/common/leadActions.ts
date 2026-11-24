import { canEdit } from "../../../app/access";
import type { LeadPlatformStatus, Me, PersonRef } from "../../../shared/api/generated/model";

/** Что сотрудник видит в меню лида (LH-1). Право на действие решает CRM; здесь — что не показывать зря. */
export interface LeadActionRules {
  /** «Заключено» и «Отказ»: лид взят этим сотрудником (или администратором) */
  close: boolean;
  /** «Спам», «Тест», «Дубль»: лид закрыт не клиентом и не у другого сотрудника */
  discard: boolean;
  /** Правка контактов: лид ничей или у этого сотрудника */
  edit: boolean;
  /** «Открыть заново»: лид закрыт отказом или стал клиентом */
  reopen: boolean;
}

const CLOSED: readonly LeadPlatformStatus[] = ["client", "lost"];

/** Правила для карточки лида «Клиенты · Лиды» по статусу Платформы и ведущему. */
export function leadActionRules(
  me: Me,
  assigned: PersonRef | null,
  status: LeadPlatformStatus,
): LeadActionRules {
  const works = canEdit(me, "crm.leads");
  const isAdmin = canEdit(me, "admin");
  const mine = assigned !== null && (assigned.id === me.id || isAdmin);
  const free = assigned === null || mine;
  const active = !CLOSED.includes(status);
  return {
    close: works && active && mine,
    discard: works && active && free,
    edit: works && free,
    reopen: works && CLOSED.includes(status),
  };
}

/** Правила для диалога «Ждут ответа»: режим `manager` — лид взят, `assigned` — кто ведёт. */
export function dialogActionRules(
  me: Me,
  mode: "bot" | "waiting" | "manager",
  assigned: PersonRef | null,
): Pick<LeadActionRules, "close" | "discard"> & { reassign: boolean } {
  const works = canEdit(me, "crm.leads");
  const mine =
    mode === "manager" && assigned !== null && (assigned.id === me.id || canEdit(me, "admin"));
  return {
    close: works && mine,
    discard: works && (mode !== "manager" || mine),
    reassign: works && mine,
  };
}
