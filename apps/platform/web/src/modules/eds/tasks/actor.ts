import { useSearchParams } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";

/**
 * За кого открыт рабочий экран поручения (СЦ-9). Строка очереди замещаемого ведёт на `?for=<id>&forName=<имя>`: в
 * карточке письма признака замещения нет, а поручение и перенос срока ищутся по человеку. Адрес только выбирает, чей
 * шаг показать; право действовать за него проверяет EDS.
 */
export function useActor(): { id: string; forName: string | null } {
  const { me } = useAuth();
  const [search] = useSearchParams();
  const forId = search.get("for");
  return forId ? { id: forId, forName: search.get("forName") } : { id: me.id, forName: null };
}
