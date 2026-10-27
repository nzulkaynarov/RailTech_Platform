import { useTranslation } from "react-i18next";

import { canEdit } from "../../app/access";
import type { Me } from "../../shared/api/generated/model";

/** Виды «С чего начать». Определяются по разделам каталога, которые сотруднику доступны для работы, а не по кодам ролей. */
export const START_KINDS = [
  "admin",
  "director",
  "manager",
  "supply",
  "engineer",
  "accountant",
] as const;
export type StartKind = (typeof START_KINDS)[number] | "default";

const KIND_RESOURCES: Readonly<Record<(typeof START_KINDS)[number], readonly string[]>> = {
  admin: ["admin"],
  director: ["eds.inbox", "eds.memo.approve"],
  manager: ["crm.leads", "crm.clients"],
  supply: ["erp.calc.goods"],
  engineer: ["erp.calc.services"],
  accountant: ["eds.payments"],
};

/**
 * Виды работы сотрудника по правам «полный» на разделы (пользовательские роли тоже: у «Кассира» с `eds.payments: full`
 * будет «Бухгалтер»). Порядок — как в `START_KINDS`; ни одного — «любая роль».
 */
export function startKindsOf(me: Me): StartKind[] {
  const kinds = START_KINDS.filter((kind) =>
    KIND_RESOURCES[kind].some((resource) => canEdit(me, resource)),
  );
  return kinds.length > 0 ? kinds : ["default"];
}

/** Роли сотрудника словами через запятую (как их запишет в обращение BFF): «Менеджер, Бухгалтер». */
export function rolesText(me: Me): string {
  return me.roles.map((role) => role.name).join(", ");
}

/** Шаги вида «С чего начать» из словаря (`help:start.kinds.<вид>.steps`). */
export function useStartSteps(kind: StartKind): string[] {
  const { t } = useTranslation("help");
  return t(`start.kinds.${kind}.steps`, { returnObjects: true }) as string[];
}
