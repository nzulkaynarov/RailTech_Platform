import { useTranslation } from "react-i18next";

import { canEdit } from "../../app/access";
import type { Me } from "../../shared/api/generated/model";

/**
 * Виды «С чего начать». Определяются по разделам каталога, которые сотруднику доступны для работы (`KIND_SECTIONS`), а не
 * по кодам и названиям ролей: роль — зона ответственности плюс набор прав (ЕВ-5а, отчёт 2026-11-22 §4.3 строка 7).
 */
export const START_KINDS = [
  "admin",
  "director",
  "manager",
  "supply",
  "engineer",
  "accountant",
  "registrar",
  "lawyer",
  "signer",
] as const;
export type StartKindName = (typeof START_KINDS)[number];
export type StartKind = StartKindName | "default";

interface KindSections {
  /** Вид у того, у кого любой из этих разделов — «полный». */
  readonly any: readonly string[];
  /** Вид не нужен тому, у кого полный любой из этих разделов: его уже ведёт текст другого вида (решающему директору — решения). */
  readonly unless?: readonly string[];
}

export const KIND_SECTIONS: Readonly<Record<StartKindName, KindSections>> = {
  admin: { any: ["admin"] },
  director: { any: ["eds.inbox", "eds.memo.approve"] },
  manager: { any: ["crm.leads", "crm.clients"] },
  supply: { any: ["erp.calc.goods"], unless: ["eds.inbox"] },
  engineer: { any: ["erp.calc.services"], unless: ["eds.inbox"] },
  accountant: { any: ["eds.payments"] },
  // Делопроизводитель: регистрация входящих и первая линия по лидам; кто сам накладывает резолюции — «директор».
  registrar: { any: ["eds.inbox.register", "crm.leads.triage"], unless: ["eds.inbox"] },
  // Юрист: виза на договор.
  lawyer: { any: ["eds.visa.legal"] },
  // Подписант: раздел «Права подписи»; у администратора тот же раздел покрыт его текстом.
  signer: { any: ["eds.signing.manage"], unless: ["admin"] },
};

/** Виды из разделов, у которых нет приоритетного вида «Главной»: у них свои тексты и в «Задачах». */
export const SECTION_ONLY_KINDS = ["registrar", "lawyer", "signer"] as const;
export type SectionOnlyKind = (typeof SECTION_ONLY_KINDS)[number];

/** Вид положен сотруднику по его разделам (одна функция для «С чего начать» и пустой «Главной»). */
export function hasKind(me: Me, kind: StartKindName): boolean {
  const { any, unless } = KIND_SECTIONS[kind];
  return any.some((r) => canEdit(me, r)) && !(unless ?? []).some((r) => canEdit(me, r));
}

/**
 * Виды работы сотрудника по правам «полный» на разделы (пользовательские роли тоже: у «Кассира» с `eds.payments: full`
 * будет «Бухгалтер»). Порядок — как в `START_KINDS`; ни одного — «любая роль».
 */
export function startKindsOf(me: Me): StartKind[] {
  const kinds = START_KINDS.filter((kind) => hasKind(me, kind));
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

/**
 * Шаги приветствия первого входа: у сотрудника с несколькими видами — по несколько шагов от каждого, всего не больше
 * `limit` (один вид — его первые `limit` шагов).
 */
export function mergeSteps(lists: readonly (readonly string[])[], limit: number): string[] {
  if (lists.length === 0) return [];
  const each = Math.max(1, Math.floor(limit / lists.length));
  return lists.flatMap((steps) => steps.slice(0, each));
}

export function useWelcomeSteps(kinds: readonly StartKind[], limit: number): string[] {
  const { t } = useTranslation("help");
  return mergeSteps(
    kinds.map((kind) => t(`start.kinds.${kind}.steps`, { returnObjects: true }) as string[]),
    limit,
  );
}
