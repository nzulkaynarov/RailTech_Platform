import { useEffect, useRef, useState } from "react";

import type { EdsFile } from "../../../shared/api/generated/model";
import {
  copyInboundMailFilesToEds,
  getInboundMail,
} from "../../../shared/api/generated/platform-bff";
import { prefillFromMail } from "../mail/mailModel";
import type { RegisterValues } from "./registerModel";

export interface MailPrefill {
  state: "idle" | "loading" | "done" | "files_failed" | "failed";
  subject?: string;
  sender?: string;
}

/**
 * «Зарегистрировать ВХ» из очереди «Входящая почта» (W18A-P2): форма P8 открывается с данными письма, а его вложения
 * BFF один раз переносит в EDS файлами сотрудника. Вложения не перенеслись — форма всё равно заполнена, файлы можно
 * приложить вручную.
 */
export function useMailPrefill(
  mailId: number | null,
  apply: (update: (prev: RegisterValues) => RegisterValues) => void,
): MailPrefill {
  const [prefill, setPrefill] = useState<MailPrefill>({ state: mailId ? "loading" : "idle" });
  const started = useRef<number | null>(null);
  useEffect(() => {
    if (mailId === null || started.current === mailId) return;
    started.current = mailId;
    void (async () => {
      try {
        const mail = await getInboundMail(mailId);
        let files: EdsFile[] = [];
        let filesFailed = false;
        if (mail.attachments.length > 0) {
          try {
            files = await copyInboundMailFilesToEds(mailId);
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
      } catch {
        setPrefill({ state: "failed" });
      }
    })();
  }, [mailId, apply]);
  return prefill;
}
