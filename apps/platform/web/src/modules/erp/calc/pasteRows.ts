import type { CalcProposalLine } from "../../../shared/api/generated/model";

/**
 * Вставка строк из Excel (план 1.1): таблица из буфера обмена — строки через перевод строки, столбцы через табуляцию.
 * Разбирается сразу, без ИИ: код решает по шапке (если она есть) или по виду столбцов. Не таблица — `null`, и текст
 * уходит на ИИ-разбор как обычно.
 */

type Column = "name" | "quantity" | "unit" | "article" | "note";

const HEADERS: Record<Column, readonly string[]> = {
  name: ["наимен", "товар", "позиц", "назван", "name", "item", "description", "nomi", "mahsulot"],
  quantity: ["кол", "qty", "quantity", "count", "soni", "miqdor"],
  unit: ["ед", "unit", "uom", "birlik", "o‘lchov", "o'lchov"],
  article: ["артикул", "код", "sku", "mpn", "article", "part", "гост", "kod"],
  note: ["примеч", "коммент", "note", "comment", "izoh"],
};

const MAX_ROWS = 500;

function cells(line: string): string[] {
  return line.split("\t").map((cell) => cell.trim());
}

function asQuantity(value: string): number | null {
  const normalized = value.replace(/\s/g, "").replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(normalized)) return null;
  const number = Math.ceil(Number(normalized));
  return number >= 1 ? number : null;
}

function headerColumns(row: string[]): Partial<Record<Column, number>> | null {
  const found: Partial<Record<Column, number>> = {};
  row.forEach((cell, index) => {
    const lower = cell.toLowerCase();
    for (const column of Object.keys(HEADERS) as Column[]) {
      if (found[column] === undefined && HEADERS[column].some((word) => lower.startsWith(word))) {
        found[column] = index;
        return;
      }
    }
  });
  return found.name !== undefined && found.quantity !== undefined ? found : null;
}

/** Без шапки: название — самый длинный текстовый столбец, количество — первый числовой, единица — короткий текст за ним. */
function guessedColumns(rows: string[][]): Partial<Record<Column, number>> | null {
  const width = Math.max(...rows.map((row) => row.length));
  const numeric: number[] = [];
  const textLength: number[] = [];
  for (let index = 0; index < width; index += 1) {
    const values = rows.map((row) => row[index] ?? "").filter(Boolean);
    numeric.push(
      values.filter((value) => asQuantity(value) !== null).length / Math.max(values.length, 1),
    );
    textLength.push(
      values.reduce((sum, value) => sum + (asQuantity(value) === null ? value.length : 0), 0),
    );
  }
  const quantity = numeric.findIndex((share) => share >= 0.8);
  if (quantity < 0) return null;
  let name = -1;
  textLength.forEach((length, index) => {
    if (index !== quantity && (name < 0 || length > (textLength[name] ?? 0))) name = index;
  });
  if (name < 0) return null;
  const unit = quantity + 1 < width && quantity + 1 !== name ? quantity + 1 : undefined;
  return { name, quantity, ...(unit !== undefined ? { unit } : {}) };
}

export function pastedRows(text: string): CalcProposalLine[] | null {
  const lines = text
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .slice(0, MAX_ROWS + 1);
  if (
    lines.length === 0 ||
    lines.filter((line) => line.includes("\t")).length < lines.length * 0.8
  ) {
    return null;
  }
  let rows = lines.map(cells);
  const header = rows[0] ? headerColumns(rows[0]) : null;
  if (header) rows = rows.slice(1);
  const columns = header ?? guessedColumns(rows);
  if (!columns || columns.name === undefined || columns.quantity === undefined) return null;
  const pick = (row: string[], column: Column) => {
    const index = columns[column];
    return index === undefined ? "" : (row[index] ?? "");
  };
  const result: CalcProposalLine[] = [];
  for (const row of rows.slice(0, MAX_ROWS)) {
    const name = pick(row, "name");
    if (!name) continue;
    result.push({
      name: name.slice(0, 500),
      quantity: asQuantity(pick(row, "quantity")) ?? 1,
      unit: pick(row, "unit").slice(0, 32),
      article: pick(row, "article").slice(0, 120),
      note: pick(row, "note").slice(0, 1000),
    });
  }
  return result.length ? result : null;
}
