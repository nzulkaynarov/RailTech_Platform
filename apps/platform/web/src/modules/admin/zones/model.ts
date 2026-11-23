import { RESOURCES } from "../../../app/rbac.generated";
import type { ZoneText } from "../../../shared/api/generated/model";

type Lang = "ru" | "uz" | "en";

export const langOf = (language: string): Lang => {
  const code = language.slice(0, 2);
  return code === "uz" || code === "en" ? code : "ru";
};

/** Название или описание зоны на языке интерфейса. */
export const zoneText = (text: ZoneText, language: string): string => text[langOf(language)];

/** Подпись раздела каталога прав на языке интерфейса; неизвестный ключ показывается как есть. */
export function sectionLabel(key: string, language: string): string {
  const def = (RESOURCES as Record<string, { label: ZoneText } | undefined>)[key];
  return def ? def.label[langOf(language)] : key;
}

export const sectionOptions = (language: string) =>
  Object.keys(RESOURCES).map((key) => ({ value: key, label: sectionLabel(key, language) }));

/** Слаг зоны из английского названия: латиница, цифры и `_`, начинается с буквы, до 40 знаков. */
export function slugOf(name: string): string {
  const base = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40)
    .replace(/_+$/g, "");
  return /^[a-z][a-z0-9_]{1,39}$/.test(base) ? base : `zone_${Date.now().toString(36)}`;
}
