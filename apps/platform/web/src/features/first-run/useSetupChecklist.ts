import { getSetupChecklist, useGetSetupChecklist } from "../../shared/api/generated/platform-bff";
import { withTimeout } from "../../shared/api/timeout";

/**
 * Чек-лист первого запуска (BFF `GET /setup/checklist`, раздел `admin` полный). `enabled` — права: без раздела запрос не
 * уходит вовсе (BFF ответил бы 403). Свежесть — полминуты: шаги меняются на других экранах Admin, и после возврата на
 * вкладку (`refetchOnWindowFocus`) баннер уже видит итог; `fresh` (мастер) — всегда перечитывать при открытии. У запроса есть предел ожидания (`REQUEST_TIMEOUT`): экран не
 * висит на загрузке, а предлагает повторить.
 */
export function useSetupChecklist(enabled: boolean, options: { fresh?: boolean } = {}) {
  return useGetSetupChecklist({
    query: {
      enabled,
      // Мастер перечитывает состояние при каждом открытии: шаг «ERP» делается на другом экране, и вернувшийся
      // администратор не должен видеть прежнее «сначала подключите ERP».
      staleTime: options.fresh ? 0 : 30_000,
      retry: false,
      queryFn: ({ signal }) => getSetupChecklist({ signal: withTimeout(signal) }),
    },
  });
}
