import { admin } from "./ru/admin";
import { clients } from "./ru/clients";
import { core } from "./ru/core";
import { integrations } from "./ru/integrations";
import { leads } from "./ru/leads";

/** Тексты интерфейса CRM (команда работает на русском; CLAUDE.md §4 — без хардкода в компонентах).
 * Разделы — в `ru/*.ts`, чтобы словарь не превышал лимит файла. */
export const ru = { ...core, ...leads, ...admin, ...clients, ...integrations };

export type Dictionary = typeof ru;
export const t = ru;

export function errorText(code: string | undefined, fallback?: string): string {
  return (code && ru.errors[code]) ?? fallback ?? ru.errors.generic ?? "";
}
