/** Размер копии по-русски: 1 024 → «1,0 КБ». */
const UNITS = ["Б", "КБ", "МБ", "ГБ", "ТБ"];

export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const text = unit === 0 ? String(value) : value.toFixed(1).replace(".", ",");
  return `${text} ${UNITS[unit] ?? ""}`;
}
