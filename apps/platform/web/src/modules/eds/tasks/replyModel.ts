import type { LetterCard, LetterReply } from "../../../shared/api/generated/model";

/** Есть ли у входящего свой черновик ответа (не передан на регистрацию): «Подготовить ответ» превращается в «Продолжить ответ». */
export function ownDraftReply(letter: LetterCard, meId: string): LetterReply | undefined {
  return (letter.replies ?? []).find((r) => r.state === "draft" && r.author.id === meId);
}
