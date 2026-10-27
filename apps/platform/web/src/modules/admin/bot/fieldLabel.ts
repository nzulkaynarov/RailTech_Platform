import type { TFunction } from "i18next";

import type { JsonSchema } from "./schemaForm";

/** Подпись поля: словарь языка интерфейса, иначе заголовок схемы CRM, иначе ключ (тест-сторож — все поля схем есть в словаре). */
export function fieldLabel(t: TFunction, key: string, schema: JsonSchema): string {
  return t(`bot:fields.${key}`, { defaultValue: schema.title ?? key });
}
