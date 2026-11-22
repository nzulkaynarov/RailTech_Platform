/**
 * Охранник «человеческого текста» (СЦ-7): после каждого теста экран не должен показывать то, что человеку читать нельзя —
 * сырые ключи перевода и коды событий (`file.attached`), даты ISO (`2026-11-22`), суммы без разрядов (`1500000.00`),
 * «строк(и)»/«назначен(а)» и внутренние номера «#2». Сам скан — чистая функция, чтобы её проверял свой тест.
 * Известные нарушения, которые не относятся к СЦ-7, — в `humanTextAllowList.ts` с причиной.
 */

export type HumanTextKind = "key" | "iso-date" | "bare-amount" | "plural-hack" | "internal-number";

export interface HumanTextFinding {
  kind: HumanTextKind;
  /** Найденный фрагмент */
  text: string;
}

/** Хвосты адресов, почты и имён файлов: `partner.example`, `sales@demo.uz`, `scan.pdf` — не ключи перевода. */
const NOT_A_KEY_TAIL = new Set([
  "com",
  "uz",
  "ru",
  "org",
  "net",
  "io",
  "example",
  "test",
  "local",
  "localhost",
  "pdf",
  "doc",
  "docx",
  "xls",
  "xlsx",
  "csv",
  "txt",
  "rtf",
  "zip",
  "png",
  "jpg",
  "jpeg",
  "gif",
  "svg",
  "webp",
  "json",
  "xml",
  "html",
  "js",
  "ts",
  "md",
  "yaml",
  "yml",
  "eml",
  "msg",
  "pfx",
  "p12",
  "pem",
  "cer",
  "crt",
  "key",
  "dwg",
  "odt",
]);

/** Точечный идентификатор строчными латинскими: минимум два сегмента по две буквы и больше. */
const DOTTED =
  /(?<![\w@/.:#-])[a-z][a-zA-Z0-9]+(?:_[a-zA-Z0-9]+)*(?:\.[a-z][a-zA-Z0-9]+(?:_[a-zA-Z0-9]+)*)+(?![\w@/-])/g;
const ISO_DATE = /(?<![\w-])\d{4}-\d{2}-\d{2}(?![\w-])/g;
const BARE_AMOUNT = /(?<![\d.,])\d{5,}\.\d{2}(?![\d])/g;
const PLURAL_HACK = /[а-яё]\((?:и|а|ы|я)\)/gi;
const INTERNAL_NUMBER = /(?<![\w&])#\d+\b/g;

function collect(kind: HumanTextKind, pattern: RegExp, text: string): HumanTextFinding[] {
  return [...text.matchAll(pattern)].map((m) => ({ kind, text: m[0] }));
}

/**
 * Текст, который человек видит на экране: текстовые узлы через пробел (соседние ячейки «860» и «12.00» не склеиваются
 * в «86012.00»), без `<script>`/`<style>` и без скрытого (`hidden`) — свёрнутых секций форм.
 */
export function visibleText(root: Node): string {
  const parts: string[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      for (let el = node.parentElement; el; el = el.parentElement) {
        if (["SCRIPT", "STYLE", "NOSCRIPT"].includes(el.tagName) || el.hasAttribute("hidden")) {
          return NodeFilter.FILTER_REJECT;
        }
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.textContent) parts.push(node.textContent);
  }
  return parts.join(" ");
}

/** Всё, что в тексте экрана не должен читать человек. */
export function scanHumanText(text: string): HumanTextFinding[] {
  const keys = collect("key", DOTTED, text).filter(({ text: token }) => {
    // `ok.pdf` + размер «1» в соседнем узле склеиваются в `ok.pdf1`: цифры в хвосте не считаем
    const tail = token.slice(token.lastIndexOf(".") + 1).replace(/\d+$/, "");
    return !NOT_A_KEY_TAIL.has(tail);
  });
  return [
    ...keys,
    ...collect("iso-date", ISO_DATE, text),
    ...collect("bare-amount", BARE_AMOUNT, text),
    ...collect("plural-hack", PLURAL_HACK, text),
    ...collect("internal-number", INTERNAL_NUMBER, text),
  ];
}

/**
 * Ключи без перевода и без `defaultValue` (даже пустого: «подсказки нет» — осознанный ответ), собранные
 * `missingKeyHandler` за один тест (`ns:key`). Без `defaultValue` i18next подставляет в запасное значение сам ключ.
 */
export const missingKeys = new Set<string>();

export function recordMissingKey(
  namespace: string,
  key: string,
  options: { defaultValue?: unknown } | undefined,
): void {
  if (typeof options?.defaultValue === "string") return;
  missingKeys.add(`${namespace}:${key}`);
}

/**
 * Что в тесте с этим текстом экрана и ключами без перевода не снято списком допустимых: пустой результат — тест чист.
 * `file` — путь тестового файла (допустимое сверяется по его фрагменту).
 */
export function humanTextProblems(
  file: string,
  text: string,
  missing: ReadonlySet<string>,
  allowed: readonly { file: string; kind: HumanTextKind; text: string }[],
  allowedKeys: readonly { file: string; key: string }[],
): string[] {
  const problems: string[] = [];
  for (const key of missing) {
    if (!allowedKeys.some((a) => file.includes(a.file) && a.key === key)) {
      problems.push(`нет перевода: ${key}`);
    }
  }
  for (const finding of scanHumanText(text)) {
    if (
      !allowed.some(
        (a) => file.includes(a.file) && a.kind === finding.kind && a.text === finding.text,
      )
    ) {
      problems.push(`${finding.kind}: «${finding.text}»`);
    }
  }
  return [...new Set(problems)];
}
