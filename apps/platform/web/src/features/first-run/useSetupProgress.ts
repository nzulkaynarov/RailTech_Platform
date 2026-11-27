import { canEdit } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { progress, visibleSteps } from "../../entities/setup/steps";
import { cardFact } from "../../entities/status/facts";
import type { IntegrationCardKey, StatusFact } from "../../shared/api/generated/model";
import {
  useGetIntegrationsOverview,
  useGetSetupCabinet,
  useGetSigningSetupHint,
} from "../../shared/api/generated/platform-bff";
import { useSetupChecklist } from "./useSetupChecklist";

const CARDS: readonly IntegrationCardKey[] = ["erp", "telegram", "mail", "models"];

/**
 * Прогресс первого запуска по шагам, которые видит администратор (СЦ-3): чек-лист BFF, адрес кабинета и права подписи.
 * Права подписи спрашиваются только у того, кто вправе их выдавать (BFF требует полный раздел), иначе строки нет.
 * Слово «Работает» у шагов служб — из обзора «Сервисов» (`entities/status`): сохранённое без проверки шага не готовит.
 */
export function useSetupProgress(enabled: boolean, options: { fresh?: boolean } = {}) {
  const { me } = useAuth();
  const checklist = useSetupChecklist(enabled, options);
  const cabinet = useGetSetupCabinet({ query: { enabled, staleTime: 30_000, retry: false } });
  const signingAllowed = enabled && canEdit(me, "eds.signing.manage");
  const signing = useGetSigningSetupHint({
    query: { enabled: signingAllowed, staleTime: 30_000, retry: false },
  });
  const overview = useGetIntegrationsOverview({
    query: { enabled, staleTime: 30_000, retry: false },
  });
  const facts: Partial<Record<IntegrationCardKey, StatusFact>> = Object.fromEntries(
    CARDS.map((key) => [key, cardFact(overview.data, key)]),
  );
  const data = checklist.data;
  // Пока обзор «Сервисов» не ответил, слова шагов служб неизвестны: список не строим (не «Готово» на мигание)
  const steps =
    data && !overview.isPending
      ? visibleSteps(data, {
          cabinetUrl: cabinet.data ? (cabinet.data.url ?? null) : undefined,
          signing: signingAllowed && signing.data ? signing.data.has_authorities : undefined,
          facts,
        })
      : [];
  return { checklist, overview, steps, ...progress(steps) };
}
