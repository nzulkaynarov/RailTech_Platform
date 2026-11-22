import { PERMISSION_SECTIONS, RESOURCES } from "../../app/rbac.generated";
import { ApiError } from "../api/errors";
import i18n from "../i18n";

type Lang = "ru" | "uz" | "en";

function currentLang(): Lang {
  const lang = (i18n.resolvedLanguage ?? "ru").slice(0, 2);
  return lang === "uz" || lang === "en" ? lang : "ru";
}

/**
 * Section of the catalog (`platform-rbac.yaml` label, in the employee's language) that a 403 names: the BFF passes the EDS
 * permission code in `details.permission`. `null` — no code or the catalog does not know it: callers fall back to the
 * general sentence, never show the code.
 */
export function missingSectionName(error: unknown, lang: Lang = currentLang()): string | null {
  if (!(error instanceof ApiError) || error.status !== 403) return null;
  const permission = error.details["permission"];
  if (typeof permission !== "string") return null;
  const key = (PERMISSION_SECTIONS as Record<string, keyof typeof RESOURCES>)[permission];
  return key ? RESOURCES[key].label[lang] : null;
}
