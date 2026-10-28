import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { useAuth } from "../../app/auth/useAuth";
import type { Me, WhatsNewMark } from "../../shared/api/generated/model";
import { getGetMeQueryKey, useMarkWhatsNew } from "../../shared/api/generated/platform-bff";
import { LATEST_WHATS_NEW, isNewer } from "./changelog";

/**
 * «Что нового» сотрудника (W-REL): отметки хранит CRM (`Me.whats_new_shown`, `Me.whats_new_read`, `PUT /me/whats-new`),
 * не браузер — окно «Платформа обновлена» каждый видит один раз на любом устройстве.
 *
 * - `fresh` — есть запись новее открытой: отметка «Новое» у «?», пока сотрудник не откроет «Что нового»;
 * - `noticeDue` — окно о новой записи ещё не показывали (и приветствие первого входа уже закрыто);
 * - `mark` — отметка сразу в кэше профиля (окно и отметка исчезают без ожидания ответа), затем в CRM.
 */
export function useWhatsNew(latest: string | undefined = LATEST_WHATS_NEW) {
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const mutation = useMarkWhatsNew({
    mutation: {
      onSuccess: (next) => {
        // Берём из ответа только отметки: остальной профиль в кэше мог уже измениться (роль, язык).
        queryClient.setQueryData<Me>(getGetMeQueryKey(), (prev) =>
          prev
            ? {
                ...prev,
                whats_new_shown: next.whats_new_shown ?? null,
                whats_new_read: next.whats_new_read ?? null,
              }
            : next,
        );
      },
    },
  });
  const fresh = isNewer(me.whats_new_read, latest);
  const noticeDue = me.onboarding_done && fresh && isNewer(me.whats_new_shown, latest);

  const { mutate } = mutation;
  const mark = useCallback(
    (data: WhatsNewMark) => {
      queryClient.setQueryData<Me>(getGetMeQueryKey(), (prev) =>
        prev
          ? {
              ...prev,
              ...(data.shown ? { whats_new_shown: data.shown } : {}),
              ...(data.read ? { whats_new_read: data.read, whats_new_shown: data.read } : {}),
            }
          : prev,
      );
      mutate({ data });
    },
    [mutate, queryClient],
  );
  return { latest, fresh, noticeDue, mark };
}
