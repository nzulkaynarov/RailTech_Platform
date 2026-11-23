import { useEffect, useRef } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import {
  getCrmRequestCallNote,
  useCreateCrmRequestCallNote,
} from "../../../shared/api/generated/platform-bff";
import type { RequestCallNoteIn } from "../../../shared/api/generated/model";
import { ApiError } from "../../../shared/api/errors";
import { LANGUAGES, type Language } from "../../../shared/i18n";
import type { LetterFile } from "./formModel";

/** Записка строится в воркере EDS (секунды): состояние опрашивается, пока не `ready` или `failed`. */
export const CALL_NOTE_POLL_MS = 1000;
const CALL_NOTE_POLL_LIMIT = 60;

/** «call» — «Записка о звонке», «request» — «Записка о запросе» (лид с сайта, из Кабинета, Telegram): тексты по контексту. */
export type NoteKind = "call" | "request";
export const noteContext = (kind: NoteKind) => (kind === "request" ? "request" : undefined);

/** Язык записки — язык интерфейса сотрудника. */
export function noteLanguage(language: string): Language {
  const base = language.slice(0, 2);
  return (LANGUAGES as readonly string[]).includes(base) ? (base as Language) : "ru";
}

/** Причина словами: подкод ответа (`call_note_no_consent`, `letterhead_missing`), иначе общий текст. */
function reasonOf(t: TFunction, error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (typeof reason === "string") {
      const text = t(`request:letter.noteReasons.${reason}`, { defaultValue: "" });
      if (text) return text;
    }
  }
  return t("request:letter.noteReasons.generic");
}

const sleep = (ms: number) =>
  new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });

/**
 * «Записка о звонке» как основание заявки: `start` заказывает записку у BFF (он берёт данные лида из CRM или принимает поля
 * формы), опрашивает готовность и отдаёт форме `LetterFile` с `kind: "call_note"` — «собираем», «готово» или причину, по
 * которой записку не собрать (нет бланка, нет согласия, канал не «звонок»).
 */
export function useCallNote(onChange: (letter: LetterFile) => void, kind: NoteKind = "call") {
  const { t } = useTranslation("request");
  const create = useCreateCrmRequestCallNote();
  const alive = useRef(true);
  // Состояние не пишется после закрытия формы; эффект выставляет флаг заново (повторный монтаж StrictMode).
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const failed = (error: string): LetterFile => ({
    name: "",
    status: "error",
    kind: "call_note",
    error,
  });

  const start = async (body: RequestCallNoteIn): Promise<void> => {
    onChange({ name: "", status: "uploading", kind: "call_note" });
    try {
      let note = await create.mutateAsync({ data: body });
      for (let i = 0; note.status === "pending" && i < CALL_NOTE_POLL_LIMIT; i += 1) {
        await sleep(CALL_NOTE_POLL_MS);
        if (!alive.current) return;
        note = await getCrmRequestCallNote(note.id);
      }
      if (!alive.current) return;
      if (note.status === "ready" && note.file) {
        onChange({ name: note.file.name, status: "done", id: note.file.id, kind: "call_note" });
      } else {
        onChange(
          failed(
            t("letter.noteFailed", {
              context: noteContext(kind),
              reason: t("letter.noteReasons.generic"),
            }),
          ),
        );
      }
    } catch (error: unknown) {
      if (!alive.current) return;
      onChange(
        failed(t("letter.noteFailed", { context: noteContext(kind), reason: reasonOf(t, error) })),
      );
    }
  };

  return { start };
}
