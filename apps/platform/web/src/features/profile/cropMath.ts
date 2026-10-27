/**
 * Геометрия обрезки фото по кругу (W15-H6). Окно обрезки — квадрат `view` px; картинка масштабируется так, чтобы
 * закрывать окно целиком (`cover`), и сдвигается мышью, касанием или стрелками. Чистые функции — тестируются без canvas.
 */

export const MIN_ZOOM = 1;
export const MAX_ZOOM = 4;
/** Сторона итоговой картинки: достаточно для рейла и чатов, файл остаётся малым. */
export const OUTPUT_SIZE = 256;

export interface Offset {
  x: number;
  y: number;
}

/** Масштаб, при котором картинка ровно закрывает окно (без пустых полей). */
export function baseScale(width: number, height: number, view: number): number {
  return Math.max(view / width, view / height);
}

export function clampZoom(zoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

/** Сдвиг не должен открывать пустое поле: картинка всегда закрывает окно. */
export function clampOffset(
  width: number,
  height: number,
  view: number,
  zoom: number,
  offset: Offset,
): Offset {
  const scale = baseScale(width, height, view) * clampZoom(zoom);
  const limitX = Math.max(0, (width * scale - view) / 2);
  const limitY = Math.max(0, (height * scale - view) / 2);
  // `+ 0` убирает «минус ноль», который иначе путает сравнение и вёрстку.
  return {
    x: Math.min(limitX, Math.max(-limitX, offset.x)) + 0,
    y: Math.min(limitY, Math.max(-limitY, offset.y)) + 0,
  };
}

export interface SourceRect {
  sx: number;
  sy: number;
  size: number;
}

/** Квадрат исходной картинки, который сейчас виден в окне. */
export function sourceRect(
  width: number,
  height: number,
  view: number,
  zoom: number,
  offset: Offset,
): SourceRect {
  const scale = baseScale(width, height, view) * clampZoom(zoom);
  const o = clampOffset(width, height, view, zoom, offset);
  return {
    sx: width / 2 - (view / 2 + o.x) / scale,
    sy: height / 2 - (view / 2 + o.y) / scale,
    size: view / scale,
  };
}
