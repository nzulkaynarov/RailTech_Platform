import { useQueryClient } from "@tanstack/react-query";
import { App } from "antd";
import { useTranslation } from "react-i18next";

import { useReturnCrmLeadToBot, useTakeCrmLead } from "../../../shared/api/generated/platform-bff";
import { actionError } from "./labels";

const PREFIX = "/api/v1/crm/messages";

/** После действия: очередь, открытая переписка и бейджи меню перечитываются (переходы — по ответу сервера). */
export function useRefreshMessages(): () => void {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      predicate: (query) => {
        const key = String(query.queryKey[0]);
        return (
          key.startsWith(PREFIX) ||
          key === "/api/v1/menu-counters" ||
          key.startsWith("/api/v1/queue")
        );
      },
    });
  };
}

/** «Забрать» и «Вернуть боту»: итог словами (успех и отказ CRM — «лида уже забрал …»). */
export function useLeadActions(lead: string) {
  const { t } = useTranslation("messages");
  const { message } = App.useApp();
  const refresh = useRefreshMessages();
  const take = useTakeCrmLead({
    mutation: {
      onSuccess: () => {
        void message.success(t("actions.taken"));
        refresh();
      },
      onError: (error) => {
        void message.error(actionError(t, error));
        refresh();
      },
    },
  });
  const giveBack = useReturnCrmLeadToBot({
    mutation: {
      onSuccess: () => {
        void message.success(t("actions.returned"));
        refresh();
      },
      onError: (error) => {
        void message.error(actionError(t, error));
      },
    },
  });
  return {
    take: () => {
      take.mutate({ lead });
    },
    taking: take.isPending,
    returnToBot: () => {
      giveBack.mutate({ lead, data: {} });
    },
    returning: giveBack.isPending,
  };
}
