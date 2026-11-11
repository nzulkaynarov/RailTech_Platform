import type { ObjectKind } from "../shared/api/generated/model";
import { matchSection } from "./registry";

/**
 * Переходы из «Моей очереди», колокольчика, поиска и ленты «Сегодня» (D1-6, SPEC-v3 §6.3, §6.4): объект открывается в
 * боковом окне своего экрана на нужной вкладке, по бизнес-номеру в адресе. Адрес приходит из BFF (`ObjectRef.path`); здесь он
 * только достраивается до полного, если BFF прислал короткий: номер вместо пути карточки, без `?panel=open&tab=`. Раздел,
 * который объект не открывает (ссылка на лид — в «Все лиды», договор — в проекте), и адрес не из карты Платформы не меняются.
 */

interface Native {
  /** Какой объект открывает раздел: по нему из номера строится путь карточки */
  kind: ObjectKind;
  /** Вкладка бокового окна, на которой ждёт решение: «Резолюция», «Одобрение», «Согласование» */
  tab: string;
}

/** Ключ — `<модуль>.<раздел>`; вкладки — из `tabs` в `module.ts` модуля. */
export const DECISION_TABS: Readonly<Record<string, Native>> = {
  "eds.inbox": { kind: "letter", tab: "resolution" },
  "eds.drafts": { kind: "quote", tab: "approve" },
  "eds.approvals": { kind: "memo", tab: "agree" },
};

/** Параметры адреса, в которых лежит номер объекта, когда у раздела нет `:id` (`/crm/leads?lead=L-2041`). */
const OBJECT_PARAMS = [
  "lead",
  "request",
  "client",
  "project",
  "letter",
  "quote",
  "memo",
  "invoice",
];

/** Номер объекта из адреса: `:id` карточки или первый из `?lead=`, `?request=`… Для списка — `undefined`. */
export function objectIdOf(
  match: { objectId?: string | undefined },
  search: string,
): string | undefined {
  if (match.objectId !== undefined) return match.objectId;
  const params = new URLSearchParams(search);
  for (const name of OBJECT_PARAMS) {
    const value = params.get(name);
    if (value) return value;
  }
  return undefined;
}

export interface RouteTarget {
  module: string;
  section: string;
  /** Номер объекта из адреса (`/eds/drafts/КП-2026%2F118`, `?lead=L-2041`); для списка — `undefined` */
  objectId?: string | undefined;
}

/** Раздел и объект по адресу вида `/eds/drafts/КП-2026%2F118?panel=open`; адрес не из карты Платформы — `undefined`. */
export function routeTarget(path: string): RouteTarget | undefined {
  const [pathname = "", search = ""] = path.split("?");
  const match = matchSection(pathname, search);
  if (!match) return undefined;
  return {
    module: match.module.code,
    section: match.section.key,
    objectId: objectIdOf(match, search),
  };
}

export function objectLink(object: { kind: ObjectKind; number: string; path: string }): string {
  const target = routeTarget(object.path);
  // Адрес не из карты — как прислал BFF: 404 внутри каркаса разберёт его сам.
  if (!target) return object.path;
  const native = DECISION_TABS[`${target.module}.${target.section}`];
  if (!native) return object.path;

  const [pathname = "", search = ""] = object.path.split("?");
  let base = pathname;
  if (target.objectId === undefined) {
    // Список без карточки: номер объекта достраивается в путь, только если вид объекта тот, что открывает раздел.
    if (object.kind !== native.kind) return object.path;
    base = `${pathname.replace(/\/$/, "")}/${encodeURIComponent(object.number)}`;
  }
  const params = new URLSearchParams(search);
  const missing = !params.has("panel") || !params.has("tab");
  if (!missing && base === pathname) return object.path;
  if (!params.has("panel")) params.set("panel", "open");
  if (!params.has("tab")) params.set("tab", native.tab);
  return `${base}?${params.toString()}`;
}
