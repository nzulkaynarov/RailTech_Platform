import { canEdit } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { progress, visibleSteps } from "../../entities/setup/steps";
import {
  useGetSetupCabinet,
  useGetSigningSetupHint,
} from "../../shared/api/generated/platform-bff";
import { useSetupChecklist } from "./useSetupChecklist";

/**
 * Прогресс первого запуска по шагам, которые видит администратор (СЦ-3): чек-лист BFF, адрес кабинета и права подписи.
 * Права подписи спрашиваются только у того, кто вправе их выдавать (BFF требует полный раздел), иначе строки нет.
 */
export function useSetupProgress(enabled: boolean, options: { fresh?: boolean } = {}) {
  const { me } = useAuth();
  const checklist = useSetupChecklist(enabled, options);
  const cabinet = useGetSetupCabinet({ query: { enabled, staleTime: 30_000, retry: false } });
  const signingAllowed = enabled && canEdit(me, "eds.signing.manage");
  const signing = useGetSigningSetupHint({
    query: { enabled: signingAllowed, staleTime: 30_000, retry: false },
  });
  const data = checklist.data;
  const steps = data
    ? visibleSteps(data, {
        cabinetUrl: cabinet.data ? (cabinet.data.url ?? null) : undefined,
        signing: signingAllowed && signing.data ? signing.data.has_authorities : undefined,
      })
    : [];
  return { checklist, steps, ...progress(steps) };
}
