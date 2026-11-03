import { App } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import { inWorkByOther, useRefreshMail } from "./mailModel";

export function reasonOf(error: unknown): string {
  return error instanceof ApiError ? error.message : String(error);
}

/** Выполнить действие над письмом: успех — сообщение, список и счётчики свежие; ошибка — словами. */
export function useMailRun(reload: () => void) {
  const { t } = useTranslation("letters");
  const { message } = App.useApp();
  const refresh = useRefreshMail();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (work: () => Promise<string>, after?: () => void): Promise<void> => {
    setPending(true);
    setError(null);
    try {
      void message.success(await work());
      await refresh();
      after?.();
    } catch (failure) {
      setError(t("mail.actions.failed", { reason: reasonOf(failure) }));
      // Письмо тем временем взял коллега: экран показывает, у кого оно, и предлагает «Забрать себе».
      if (inWorkByOther(failure)) reload();
    } finally {
      setPending(false);
    }
  };
  return { run, pending, error, setError };
}

export type MailRun = ReturnType<typeof useMailRun>["run"];
