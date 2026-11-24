import { formatNumber } from "./money";

const SPACES = new RegExp(String.raw`[\s\u00a0\u202f]`, "g");

function trimZeros(text: string, separator: string): string {
  if (!text.includes(separator)) return text;
  const trimmed = text.replace(/0+$/, "");
  return trimmed.endsWith(separator) ? trimmed.slice(0, -1) : trimmed;
}

/**
 * Показ и разбор десятичного поля `InputNumber` в языке интерфейса: «18,5» (ru, uz) или «18.5» (en), без хвостового
 * нуля («18», а не «18.0»). Пока человек печатает, текст не трогаем. Значение остаётся строкой с точкой (`stringMode`).
 */
export function decimalInputProps(language: string) {
  const separator = language.startsWith("en") ? "." : ",";
  return {
    decimalSeparator: separator,
    formatter: (
      value: string | number | undefined,
      info: { userTyping: boolean; input: string },
    ) =>
      info.userTyping
        ? info.input
        : value === undefined || value === ""
          ? ""
          : trimZeros(formatNumber(value, { language }), separator).replace(SPACES, ""),
    parser: (text: string | undefined) => (text ?? "").replace(SPACES, "").replace(",", "."),
  } as const;
}
