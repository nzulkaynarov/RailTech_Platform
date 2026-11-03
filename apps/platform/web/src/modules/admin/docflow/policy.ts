export type PiiPolicy = "business" | "strict";
export const POLICIES: readonly PiiPolicy[] = ["business", "strict"];

/** Политика из значений раздела `ai` настроек CRM; нет значения — «Деловая» (по умолчанию CRM). */
export function policyOf(values: Record<string, Record<string, unknown>> | undefined): PiiPolicy {
  return values?.["ai"]?.["pii_policy"] === "strict" ? "strict" : "business";
}
