import { describe, expect, it } from "vitest";

import i18n, { resources } from "../i18n";
import {
  DICTIONARY_STATUS,
  MEANING_TONE,
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
      expect([...DICTIONARY_STATUS[kind as keyof typeof expected]].sort()).toEqual(
        [...statuses].sort(),
      );
    }
    for (const lng of ["ru", "uz", "en"] as const) {
      for (const [kind, statuses] of Object.entries(DICTIONARY_STATUS)) {
        for (const status of statuses) {
          // у каждого словарного кода есть цвет в общей карте
          expect(
            STATUS_TONE[kind as keyof typeof DICTIONARY_STATUS],
            `${kind}.${status}`,
          ).toHaveProperty(status);
          const key = statusLabelKey(kind as keyof typeof DICTIONARY_STATUS, status);
          expect(i18n.exists(key, { lng }), `${lng}: ${key}`).toBe(true);
        }
      }
    }
  });

  it("каждое слово словаря `dictionary:status` и `dictionary:stage` показывается тегом по коду", () => {
    const dictionary = resources.ru.dictionary as unknown as {
      status: Record<string, Record<string, string>>;
      stage: Record<string, string>;
    };
    const words: Record<string, readonly string[]> = DICTIONARY_STATUS;
    for (const [kind, map] of Object.entries(dictionary.status)) {
      expect([...(words[kind] ?? [])].sort(), kind).toEqual(Object.keys(map).sort());
      for (const code of Object.keys(map)) {
        expect(isKnownStatus(kind as keyof typeof DICTIONARY_STATUS, code), `${kind}.${code}`).toBe(
          true,
        );
      }
    }
    expect([...DICTIONARY_STATUS.stage].sort()).toEqual(Object.keys(dictionary.stage).sort());
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

  it("один код статуса — один цвет во всех видах и модулях (UX-2b)", () => {
    // Категории (вид позиции, происхождение записи) — не статусы: их коды с кодами статусов не сравниваются.
    const categories = new Set(["itemKind", "origin", "notification", "due"]);
    const seen = new Map<string, { tone: string; kind: string }>();
    const conflicts: string[] = [];
    for (const kind of STATUS_KINDS) {
      if (categories.has(kind)) continue;
      for (const [code, tone] of Object.entries(STATUS_TONE[kind])) {
        const before = seen.get(code);
        if (before && before.tone !== tone) {
          conflicts.push(`${code}: ${before.kind}=${before.tone}, ${kind}=${tone}`);
        }
        if (!before) seen.set(code, { tone, kind });
      }
    }
    expect(conflicts).toEqual([]);
  });

  it("смысл → цвет по SPEC-v3 §5.2: ждёт — золотой, одобрено — зелёный, отклонено — красный, отменено — серый", () => {
    expect(MEANING_TONE).toEqual({
      waiting: "gold",
      draft: "gold",
      done: "green",
      failed: "red",
      memo: "purple",
      active: "blue",
      external: "cyan",
      closed: "default",
      neutral: "default",
    });
    // Расхождения из аудита 2026-10-30: «КП одобрено», КП «у директора», «Отменён» — одинаковы в EDS и ERP.
    expect(STATUS_TONE.quote.approved).toBe("green");
    expect(STATUS_TONE.quote.at_director).toBe(STATUS_TONE.quote.open);
    expect(STATUS_TONE.quote.at_director).toBe("gold");
    expect(STATUS_TONE.supplierOrder.cancelled).toBe(STATUS_TONE.contract.cancelled);
    expect(STATUS_TONE.supplierOrder.cancelled).toBe("default");
  });

  it("снимок карты: изменение цвета статуса — осознанное (правится снимок)", () => {
    expect(STATUS_TONE).toMatchSnapshot();
  });

  it("неизвестный код — нейтральный цвет", () => {
    expect(statusTone("invoice", "paid")).toBe("green");
    expect(statusTone("invoice", "новый_код")).toBe("default");
    expect(isKnownStatus("invoice", "новый_код")).toBe(false);
  });
});
