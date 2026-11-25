import { useTranslation } from "react-i18next";

import { useCreateTelegramLink, useGetProfile } from "../../shared/api/generated/platform-bff";
import { navigateTo } from "../../shared/lib/navigate";
import { profileErrorText } from "../profile/errors";

export interface TelegramLinkLine {
  /** Строка показывается, только пока Telegram не привязан. */
  show: boolean;
  pending: boolean;
  error: string | null;
  /** Один тап: выпустить одноразовую ссылку и сразу открыть бота; привязку подтверждает бот. */
  start: () => void;
}

/**
 * «Привязать Telegram» одной строкой (ОНБ-1.3): без нового экрана и без QR. Вкладку открываем сразу по тапу (до ответа
 * сервера), иначе браузер блокирует окно, открытое после запроса; не вышло — переходим в этой же вкладке.
 */
export function useTelegramLink(): TelegramLinkLine {
  const { t } = useTranslation("profile");
  const profile = useGetProfile();
  const create = useCreateTelegramLink();
  const linked = profile.data?.telegram.linked ?? true; // пока профиль не пришёл — строки нет
  return {
    show: !linked,
    pending: create.isPending,
    error: create.isError ? profileErrorText(t, "telegram", create.error) : null,
    start: () => {
      const tab = window.open("", "_blank");
      create.mutate(undefined, {
        onSuccess: (ticket) => {
          if (tab) {
            tab.opener = null; // the bot page gets no handle to the Platform
            tab.location.href = ticket.url;
          } else navigateTo(ticket.url);
        },
        onError: () => {
          tab?.close();
        },
      });
    },
  };
}
