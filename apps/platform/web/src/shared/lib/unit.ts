/**
 * Подпись числового поля с единицей (стандарт интерфейса §8, UI-8): единица или валюта стоит внутри поля справа
 * (`suffix={unitOf(label)}`), а подпись над полем — без неё. Экранный чтец читает подпись целиком: «Квота, шт.».
 * Единица — то, что после последней запятой в строке перевода («Срок со склада, дней» → «дней»).
 */
export function splitUnit(label: string): { text: string; unit: string | null } {
  const at = label.lastIndexOf(", ");
  if (at <= 0) return { text: label, unit: null };
  return { text: label.slice(0, at), unit: label.slice(at + 2) };
}

/** Единица из подписи для `suffix` поля; нет единицы — `undefined`. */
export function unitOf(label: string): string | undefined {
  return splitUnit(label).unit ?? undefined;
}
