import type { ObjectKind } from "../shared/api/generated/model";
import { routeTarget } from "./bridge";

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

/** Ключ — `<модуль>.<раздел>` как в `bridge.ts`; вкладки — из `tabs` в `module.ts` модуля. */
export const DECISION_TABS: Readonly<Record<string, Native>> = {
  "eds.inbox": { kind: "letter", tab: "resolution" },
  "eds.drafts": { kind: "quote", tab: "approve" },
  "eds.approvals": { kind: "memo", tab: "agree" },
};

export function objectLink(object: { kind: ObjectKind; number: string; path: string }): string {
  const target = routeTarget(object.path);
  // Заглушка или адрес не из карты — как прислал BFF: «Где сделать» и 404 внутри каркаса разбирают их сами.
  if (!target || target.entry) return object.path;
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
