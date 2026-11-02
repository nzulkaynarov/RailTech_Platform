import type { LocalizedName } from "../../shared/api/generated/model";
import { useListDictionaryItems } from "../../shared/api/generated/platform-bff";

/** Справочники писем (EDS-REG): виды входящих документов и способы получения — данные администратора. */
export type LetterDictionary = "letter-kinds" | "receipt-methods";

/** Название на языке интерфейса; пустые узбекское и английское — русское. */
export function localName(name: LocalizedName, language: string): string {
  const lang = language.slice(0, 2) as keyof LocalizedName;
  return name[lang] || name.ru;
}

/**
 * Значения справочника: `includeHidden` — со скрытыми (названия у старых писем, фильтр журнала), без него — только
 * действующие (форма регистрации).
 */
export function useLetterDictionary(kind: LetterDictionary, includeHidden = false, enabled = true) {
  return useListDictionaryItems(kind, includeHidden ? { include_hidden: true } : undefined, {
    query: { staleTime: 5 * 60_000, enabled },
  });
}
