import { useGetSetupChecklist } from "../../shared/api/generated/platform-bff";

/**
 * Чек-лист первого запуска (BFF `GET /setup/checklist`, раздел `admin` полный). `enabled` — права: без раздела запрос не
 * уходит вовсе (BFF ответил бы 403). Свежесть — полминуты: шаги меняются на других экранах Admin, и после возврата на
 * вкладку (`refetchOnWindowFocus`) баннер уже видит итог.
 */
export function useSetupChecklist(enabled: boolean) {
  return useGetSetupChecklist({ query: { enabled, staleTime: 30_000, retry: false } });
}
