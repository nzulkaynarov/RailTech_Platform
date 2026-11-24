import { describe, expect, it } from "vitest";

import enLetters from "../../shared/i18n/en/letters.json";
import enPayments from "../../shared/i18n/en/payments.json";
import ruLetters from "../../shared/i18n/ru/letters.json";
import ruPayments from "../../shared/i18n/ru/payments.json";
import uzLetters from "../../shared/i18n/uz/letters.json";
import uzPayments from "../../shared/i18n/uz/payments.json";

// СЦ-8: every action code EDS writes to a journal has a word, so the history never shows a raw code like `file.attached`.
// The contract only says `JournalEntry.action` is a string by pattern, so the list is kept by hand (EDS `services/`:
// letters.py, instructions.py, files.py, documents.py).
const LETTER_ACTIONS = [
  "letter.registered",
  "letter.resolved",
  "letter.returned",
  "letter.rejected",
  "letter.resubmitted",
  "letter.draft_saved",
  "letter.executed",
  "letter.acknowledged",
  "letter.duplicate_forced",
  "letter.marked_duplicate",
  "letter.work_cancelled",
  "letter.duplicate_linked",
  "letter.closed",
  "letter.reopened",
  "letter.returned_to_author",
  "instruction.executed",
  "instruction.extension_requested",
  "instruction.extension_approved",
  "instruction.extension_rejected",
  "instruction.co_executor_added",
  "file.attached",
  "file.version_added",
];

const MEMO_ACTIONS = [
  "document.created",
  "document.submitted",
  "document.updated",
  "approval.requested",
  "approval.decided",
  "document.paid",
  "document.archived",
  "file.attached",
  "file.version_added",
];

const key = (code: string) => code.replace(".", "_");

describe("слова для кодов журнала EDS (ru/en/uz)", () => {
  it.each([
    ["ru", ruLetters.card.actions],
    ["en", enLetters.card.actions],
    ["uz", uzLetters.card.actions],
  ] as const)("журнал письма, %s: у каждого кода есть слово", (_lang, words) => {
    const missing = LETTER_ACTIONS.filter((code) => !(words as Record<string, string>)[key(code)]);
    expect(missing).toEqual([]);
  });

  it.each([
    ["ru", ruPayments.memo.journalAction],
    ["en", enPayments.memo.journalAction],
    ["uz", uzPayments.memo.journalAction],
  ] as const)("журнал записки к оплате, %s: у каждого кода есть слово", (_lang, words) => {
    const missing = MEMO_ACTIONS.filter((code) => !(words as Record<string, string>)[key(code)]);
    expect(missing).toEqual([]);
  });
});
