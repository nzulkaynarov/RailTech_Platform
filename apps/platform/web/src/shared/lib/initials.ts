/** Инициалы человека и компании для запасного вида картинки (стандарт интерфейса §12). */

const LEGAL_FORMS = new Set([
  "ооо",
  "оао",
  "зао",
  "ао",
  "пао",
  "ип",
  "чп",
  "сп",
  "уп",
  "гуп",
  "мчж",
  "мчж.",
  "mchj",
  "mchj.",
  "qk",
  "xk",
  "aj",
  "llc",
  "ltd",
  "jsc",
  "inc",
  "gmbh",
  "fe",
]);

/** Инициалы: первые буквы двух первых слов; у компании без организационной формы и кавычек. */
export function entityInitials(name: string, company = false): string {
  const words = name
    .replace(/[«»"'“”„()]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .filter((word) => !company || !LEGAL_FORMS.has(word.toLowerCase()));
  const letters = words.slice(0, 2).map((word) => Array.from(word)[0] ?? "");
  return letters.join("").toUpperCase() || "?";
}
