import type { ImapFolder, ImapFolderIn } from "../../../shared/api/generated/model";

/** Выбор папок опроса (W18A-P2-2): обычные и одна «Спам». */
export interface FolderChoice {
  regular: string[];
  spam: string | null;
}

export function choiceOf(folders: readonly ImapFolder[], mailbox: string): FolderChoice {
  const regular = folders.filter((f) => !f.spam).map((f) => f.name);
  return {
    regular: regular.length > 0 ? regular : [mailbox || "INBOX"],
    spam: folders.find((f) => f.spam)?.name ?? null,
  };
}

/** Выбор → `folders` запроса: обычные, затем «Спам» (одна папка не может быть обеими). */
export function foldersOf(choice: FolderChoice): ImapFolderIn[] {
  const regular = choice.regular.filter((name) => name !== choice.spam);
  return [
    ...regular.map((name) => ({ name, spam: false })),
    ...(choice.spam ? [{ name: choice.spam, spam: true }] : []),
  ];
}
