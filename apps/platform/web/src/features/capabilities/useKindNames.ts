import { useTranslation } from "react-i18next";

import { localName } from "../../modules/eds/dictionaries";
import { useListDictionaryItems } from "../../shared/api/generated/platform-bff";

/** Названия видов документов реестра подписи (справочник `signing-kinds`); нет доступа к справочнику — код как есть. */
export function useKindNames(enabled: boolean): (code: string) => string {
  const { i18n } = useTranslation();
  const kinds = useListDictionaryItems(
    "signing-kinds",
    { include_hidden: true },
    { query: { staleTime: 5 * 60_000, enabled } },
  );
  return (code) => {
    const found = kinds.data?.items.find((item) => item.code === code);
    return found ? localName(found.name, i18n.language) : code;
  };
}
