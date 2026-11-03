import { useTranslation } from "react-i18next";

import { canSee } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";

import type { LetterResolutionKind, LocalizedName } from "../../shared/api/generated/model";
import { useListDictionaryItems } from "../../shared/api/generated/platform-bff";

/** Справочники писем (EDS-REG): виды входящих документов и способы получения — данные администратора. */
export type LetterDictionary = "letter-kinds" | "receipt-methods" | "resolution-kinds";

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

/**
 * Названия видов резолюции (EDS-REG): поведение — закрытый список кода (`execute`, `reply`, `info`), название — справочник
 * `resolution-kinds`, его переименовывает администратор. Пока справочник не пришёл — слово из словаря интерфейса.
 */
export function useResolutionKindName(): (kind: LetterResolutionKind) => string {
  const { t, i18n } = useTranslation("letters");
  const { me } = useAuth();
  // Исполнитель поручения без раздела писем видит резолюцию, но справочник ему не положен — слово из словаря.
  const allowed = canSee(me, { anyOf: ["eds.inbox", "eds.inbox.register", "admin"] });
  const names = useLetterDictionary("resolution-kinds", false, allowed);
  return (kind) => {
    const item = names.data?.items.find((entry) => entry.code === kind);
    return item ? localName(item.name, i18n.language) : t(`office.kind.${kind}`);
  };
}
