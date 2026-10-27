import { describe, expect, it } from "vitest";

import { MAX_ZOOM, MIN_ZOOM, baseScale, clampOffset, clampZoom, sourceRect } from "./cropMath";

const VIEW = 240;

describe("обрезка фото по кругу", () => {
  it("масштаб по короткой стороне: окно закрыто целиком", () => {
    expect(baseScale(480, 960, VIEW)).toBe(0.5);
    expect(baseScale(960, 480, VIEW)).toBe(0.5);
    expect(baseScale(120, 120, VIEW)).toBe(2);
  });

  it("масштаб ограничен", () => {
    expect(clampZoom(0.2)).toBe(MIN_ZOOM);
    expect(clampZoom(9)).toBe(MAX_ZOOM);
    expect(clampZoom(2.5)).toBe(2.5);
  });

  it("квадратная картинка без сдвига: виден весь квадрат", () => {
    expect(sourceRect(480, 480, VIEW, 1, { x: 0, y: 0 })).toEqual({ sx: 0, sy: 0, size: 480 });
  });

  it("широкая картинка: по центру виден центральный квадрат", () => {
    const rect = sourceRect(960, 480, VIEW, 1, { x: 0, y: 0 });
    expect(rect).toEqual({ sx: 240, sy: 0, size: 480 });
  });

  it("увеличение сужает видимую область вокруг центра", () => {
    const rect = sourceRect(480, 480, VIEW, 2, { x: 0, y: 0 });
    expect(rect).toEqual({ sx: 120, sy: 120, size: 240 });
  });

  it("сдвиг вправо показывает левую часть картинки", () => {
    const rect = sourceRect(960, 480, VIEW, 1, { x: 100, y: 0 });
    expect(rect.sx).toBe(240 - 200);
  });

  it.each([
    [
      { x: 9999, y: 9999 },
      { x: 120, y: 0 },
    ],
    [
      { x: -9999, y: -9999 },
      { x: -120, y: 0 },
    ],
    [
      { x: 30, y: 7 },
      { x: 30, y: 0 },
    ],
  ])("сдвиг %j не открывает пустое поле → %j", (offset, expected) => {
    // 960×480 при масштабе 0,5: ширина 480 на экране, лишних 240 → ±120; по высоте запаса нет
    expect(clampOffset(960, 480, VIEW, 1, offset)).toEqual(expected);
  });

  it("квадрат всегда внутри картинки при любом сдвиге и масштабе", () => {
    for (const zoom of [1, 1.7, 3, MAX_ZOOM]) {
      for (const x of [-5000, -10, 0, 10, 5000]) {
        for (const y of [-5000, 0, 5000]) {
          const r = sourceRect(800, 600, VIEW, zoom, { x, y });
          expect(r.sx).toBeGreaterThanOrEqual(-1e-9);
          expect(r.sy).toBeGreaterThanOrEqual(-1e-9);
          expect(r.sx + r.size).toBeLessThanOrEqual(800 + 1e-9);
          expect(r.sy + r.size).toBeLessThanOrEqual(600 + 1e-9);
        }
      }
    }
  });
});
