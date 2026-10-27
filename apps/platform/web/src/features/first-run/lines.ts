import type { TFunction } from "i18next";

/** Список строк из словаря (массив в JSON): для блоков «Что произойдёт». */
export function lines(t: TFunction, key: string): string[] {
  const value: unknown = t(key, { returnObjects: true });
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}
