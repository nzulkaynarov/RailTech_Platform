import { canEdit } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { needsSetup } from "../../entities/setup/steps";
import { useSetupChecklist } from "./useSetupChecklist";

/**
 * Первый запуск ещё не завершён (W15-H4, UX-оценка §5 P1-6): есть несделанный шаг или нет своей компании. Тогда в
 * подменю Настроек виден пункт «Первый запуск»; после — экран открывается ссылкой «Настройка Платформы» в «Подключениях».
 * Только администратор (`admin` — полный): чек-лист отдаётся с этим правом. Запрос общий с баннером (тот же кэш).
 */
export function useSetupPending(): boolean {
  const { me } = useAuth();
  const allowed = canEdit(me, "admin");
  const checklist = useSetupChecklist(allowed);
  return allowed && checklist.data !== undefined && needsSetup(checklist.data);
}
