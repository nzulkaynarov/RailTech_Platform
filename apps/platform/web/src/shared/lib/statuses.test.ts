import { describe, expect, it } from "vitest";

import i18n, { resources } from "../i18n";
import {
  STAGES,
  STATUS_KINDS,
  STATUS_TONE,
  STATUS_TONES,
  TONE_STYLE,
  isKnownStatus,
  statusLabelKey,
  statusTone,
} from "./statuses";

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const [r = 0, g = 0, b = 0] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(fg: string, bg: string): number {
  const [a, b] = [luminance(fg), luminance(bg)];
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

describe("карты статусов", () => {
  it.each(STATUS_TONES)("цвет %s: текст на фоне тега ≥ 4.5:1", (tone) => {
    expect(contrast(TONE_STYLE[tone].color, TONE_STYLE[tone].background)).toBeGreaterThanOrEqual(
      4.5,
    );
  });

  it("SPEC-v3 §2.4: у каждого документа есть все статусы, у каждого статуса — слово на трёх языках", () => {
    const expected = {
      incoming: ["registered", "awaiting_resolution", "resolved", "returned", "rejected"],
      quote: ["draft", "revision", "approved", "sent", "accepted", "declined", "expired"],
      contract: ["draft", "agreed", "issued", "signed", "rejected"],
      invoice: ["issued", "proof_received", "partially_paid", "paid", "overdue"],
      act: ["draft", "issued", "signed", "returned"],
      memo: ["pending", "approved", "rejected", "returned", "passed_to_accountant", "paid"],
    } as const;
    for (const [kind, statuses] of Object.entries(expected)) {
      expect(Object.keys(STATUS_TONE[kind as keyof typeof expected]).sort()).toEqual(
        [...statuses].sort(),
      );
    }
    for (const lng of ["ru", "uz", "en"] as const) {
      for (const kind of STATUS_KINDS) {
        for (const status of Object.keys(STATUS_TONE[kind])) {
          const key = statusLabelKey(kind, status);
          expect(i18n.exists(key, { lng }), `${lng}: ${key}`).toBe(true);
        }
      }
    }
  });

  it("слова статусов в одном документе не повторяются", () => {
    const words = Object.entries(resources.ru.dictionary.status).flatMap(([kind, map]) => {
      const values = Object.values(map);
      expect(new Set(values).size, kind).toBe(values.length);
      return values;
    });
    expect(words.length).toBeGreaterThan(30);
  });

  it("стадии — те же семь шагов и «Отказ»", () => {
    expect(Object.keys(STATUS_TONE.stage)).toEqual([...STAGES, "LOST"]);
    expect(STATUS_TONE.stage.LOST).toBe("red");
  });

  it("неизвестный код — нейтральный цвет", () => {
    expect(statusTone("invoice", "paid")).toBe("green");
    expect(statusTone("invoice", "новый_код")).toBe("default");
    expect(isKnownStatus("invoice", "новый_код")).toBe(false);
  });
});
