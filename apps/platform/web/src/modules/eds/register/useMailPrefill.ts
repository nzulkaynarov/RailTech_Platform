import { useCallback, useEffect, useRef, useState } from "react";

import type { EdsFile } from "../../../shared/api/generated/model";
import {
  copyInboundMailFilesToEds,
  getInboundMail,
  takeInboundMail,
} from "../../../shared/api/generated/platform-bff";
import { inWorkByOther, prefillFromMail } from "../mail/mailModel";
import type { RegisterValues } from "./registerModel";

export interface MailPrefill {
  /** `busy` — письмо уже ведёт другой сотрудник (W18A-P2-3): регистрировать нельзя, пока не «Забрать себе» */
  state: "idle" | "loading" | "done" | "files_failed" | "failed" | "busy";
  subject?: string;
  sender?: string;
  /** Кто ведёт письмо (при `busy`) */
  holder?: { name: string; since: string | null };
  /** «Забрать себе»: письмо переходит к текущему сотруднику, форма заполняется заново */
  takeOver: () => void;
}

/**
 * «Зарегистрировать ВХ» из очереди «Входящая почта» (W18A-P2): форма P8 открывается с данными письма, а его вложения
 * BFF один раз переносит в EDS файлами сотрудника. Открытие формы — первое действие над письмом: оно берётся в работу
 * (W18A-P2-3); ведёт другой — форма не заполняется, предлагается «Забрать себе». Вложения не перенеслись — форма всё
 * равно заполнена, файлы можно приложить вручную.
 */
export function useMailPrefill(
  mailId: number | null,
  apply: (update: (prev: RegisterValues) => RegisterValues) => void,
): MailPrefill {
  const [prefill, setPrefill] = useState<Omit<MailPrefill, "takeOver">>({
    state: mailId ? "loading" : "idle",
  });
  const started = useRef<number | null>(null);
  const load = useCallback(
    async (id: number, takeover: boolean) => {
      setPrefill({ state: "loading" });
      try {
        await takeInboundMail(id, { takeover });
        const mail = await getInboundMail(id);
        let files: EdsFile[] = [];
        let filesFailed = false;
        if (mail.attachments.length > 0) {
          try {
            files = await copyInboundMailFilesToEds(id);
          } catch {
            filesFailed = true;
          }
        }
        apply((prev) => ({ ...prev, ...prefillFromMail(mail, files) }));
        setPrefill({
          state: filesFailed ? "files_failed" : "done",
          subject: mail.subject,
          sender: mail.from_name || mail.from_email,
        });
      } catch (failure) {
        const holder = inWorkByOther(failure);
        setPrefill(holder ? { state: "busy", holder } : { state: "failed" });
      }
    },
    [apply],
  );
  useEffect(() => {
    if (mailId === null || started.current === mailId) return;
    started.current = mailId;
    void load(mailId, false);
  }, [mailId, load]);
  const takeOver = useCallback(() => {
    if (mailId !== null) void load(mailId, true);
  }, [mailId, load]);
  return { ...prefill, takeOver };
}
