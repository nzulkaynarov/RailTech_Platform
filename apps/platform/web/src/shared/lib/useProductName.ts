import { useTranslation } from "react-i18next";

import { useGetSetupState } from "../api/generated/platform-bff";

/**
 * Название продукта в заголовке вкладки, у логотипа и на экране входа — из «Настройки · Компания» (CRM `company.name`,
 * задача «Н3», решение владельца 2026-11-13): в коде его нет. Не задано или запрос не удался — нейтральное «Платформа».
 * Буквы логотипа — две заглавные первого слова («RailTech» → RT), иначе первые буквы двух слов (одно слово — две буквы).
 */
export function useProductName(): { name: string; initials: string } {
  const { t } = useTranslation("common");
  const state = useGetSetupState({ query: { retry: false, staleTime: 5 * 60_000 } });
  const name = state.data?.company_name?.trim() || t("app.title");
  return { name, initials: initialsOf(name) };
}

export function initialsOf(name: string): string {
  const [first = "", second = ""] = name.match(/[\p{L}\p{N}]+/gu) ?? [];
  // «RailTech», «NovaTrade» — заглавные буквы первого слова; иначе — первые буквы двух слов
  const [c1, c2] = first.match(/\p{Lu}/gu) ?? [];
  if (c1 && c2 && /\p{Ll}/u.test(first)) return `${c1}${c2}`;
  if (second === "") return first.slice(0, 2).toUpperCase();
  return `${first.slice(0, 1)}${second.slice(0, 1)}`.toUpperCase();
}
