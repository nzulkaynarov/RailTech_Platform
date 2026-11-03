import type {
  LetterCard,
  LetterDuplicate,
  LetterDuplicateCheckIn,
  LetterDuplicateMatch,
} from "../shared/api/generated/model";

/**
 * Моки EDS-DUP: те же правила, что у EDS (`services/letter_dedup.py`) — корреспондент по ИНН или названию без регистра,
 * кавычек и формы собственности; исх. № без регистра, пробелов и «№»; дата исх. Похожие — тема за ±3 дня, исх. № с другой
 * датой. Файлы мок не сравнивает.
 */
const LEGAL = new Set(["ооо", "ooo", "000", "llc", "mchj", "мчж", "ао", "ao", "ип", "ltd", "jsc"]);
const PUNCT = /[«»"“”„'`’‘.,;:()[\]{}]/g;

export const nameKey = (value: string | null | undefined) =>
  (value ?? "")
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(PUNCT, " ")
    .split(/\s+/)
    .filter((word) => word && !LEGAL.has(word))
    .join(" ");

export const refKey = (value: string | null | undefined) =>
  (value ?? "").replace(/[№#\s]/g, "").toLowerCase();

const subjectKey = (value: string | null | undefined) =>
  (value ?? "").toLowerCase().replace(PUNCT, " ").split(/\s+/).filter(Boolean).join(" ");

function sameSender(probe: LetterDuplicateCheckIn, letter: LetterCard): boolean {
  if (probe.sender_inn && letter.sender.inn) return probe.sender_inn === letter.sender.inn;
  const name = nameKey(probe.sender_name);
  return Boolean(name) && name === nameKey(letter.sender.name);
}

function item(letter: LetterCard, match: LetterDuplicateMatch): LetterDuplicate {
  return {
    id: letter.id,
    number: letter.number,
    subject: letter.subject,
    received_at: letter.received_at,
    status: letter.status,
    registered_at: letter.registered_at,
    match,
    path: `/eds/inbox/${encodeURIComponent(letter.number)}`,
  };
}

const days = (a: string, b: string) => Math.abs(Date.parse(a) - Date.parse(b)) / 86_400_000;

/** Точное совпадение и похожие (не больше пяти, точные первыми); дубли не возвращаются. */
export function findDuplicates(
  letters: readonly LetterCard[],
  probe: LetterDuplicateCheckIn,
): LetterDuplicate[] {
  const ref = refKey(probe.sender_ref_number);
  const subject = subjectKey(probe.subject);
  const exact: LetterDuplicate[] = [];
  const similar: LetterDuplicate[] = [];
  const live = letters.filter((l) => l.status !== "duplicate" && sameSender(probe, l));
  for (const letter of [...live].sort((a, b) => a.registered_at.localeCompare(b.registered_at))) {
    const sameRef = Boolean(ref) && refKey(letter.sender_ref.number) === ref;
    if (sameRef && probe.sender_ref_date && letter.sender_ref.date === probe.sender_ref_date) {
      exact.push(item(letter, "exact"));
    } else if (sameRef) {
      similar.push(item(letter, "same_ref"));
    } else if (
      subject &&
      probe.received_at &&
      subjectKey(letter.subject) === subject &&
      days(letter.received_at, probe.received_at) <= 3
    ) {
      similar.push(item(letter, "same_subject"));
    }
  }
  return [...exact.slice(0, 1), ...similar].slice(0, 5);
}
