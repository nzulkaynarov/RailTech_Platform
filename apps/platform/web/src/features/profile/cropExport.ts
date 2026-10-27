import { OUTPUT_SIZE, type SourceRect } from "./cropMath";

/**
 * Вырезает круг из выбранной картинки: PNG 256×256 с прозрачными углами. Единственное место, где нужен canvas, —
 * в тестах jsdom подменяется заглушкой.
 */
export async function renderCircle(image: CanvasImageSource, rect: SourceRect): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = OUTPUT_SIZE;
  canvas.height = OUTPUT_SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas недоступен");
  ctx.beginPath();
  ctx.arc(OUTPUT_SIZE / 2, OUTPUT_SIZE / 2, OUTPUT_SIZE / 2, 0, Math.PI * 2);
  ctx.closePath();
  ctx.clip();
  ctx.drawImage(image, rect.sx, rect.sy, rect.size, rect.size, 0, 0, OUTPUT_SIZE, OUTPUT_SIZE);
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("не удалось получить картинку"));
    }, "image/png");
  });
}
