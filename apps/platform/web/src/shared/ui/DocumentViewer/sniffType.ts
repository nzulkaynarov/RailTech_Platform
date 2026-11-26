/** Что за файл: PDF и картинки показываются, остальное (Word, Excel) — только «Скачать». */
export function sniffType(bytes: ArrayBuffer): string | null {
  const head = new Uint8Array(bytes.slice(0, 12));
  const text = (from: number, to: number) => String.fromCharCode(...head.slice(from, to));
  if (text(0, 4) === "%PDF") return "application/pdf";
  if (head[0] === 0x89 && text(1, 4) === "PNG") return "image/png";
  if (head[0] === 0xff && head[1] === 0xd8) return "image/jpeg";
  if (text(0, 4) === "RIFF" && text(8, 12) === "WEBP") return "image/webp";
  return null;
}
