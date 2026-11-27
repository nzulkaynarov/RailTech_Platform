import { describe, expect, it } from "vitest";

import type { IntegrationsOverview, StatusFact } from "../../shared/api/generated/model";
import { STEP_CARD, UNKNOWN_FACT, cardFact, isReady, stepVerdict } from "./facts";

const fact = (state: StatusFact["state"]): StatusFact => ({
  state,
  checked_at: "2026-11-27T09:57:00Z",
  source: "check",
  live: state === "works",
});

describe("слово шага мастера и готовности (одна функция на четыре места)", () => {
  it.each([
    ["done", "works", true, "works"],
    ["done", "not_verified", true, "not_verified"],
    ["done", "stale", true, "stale"],
    ["done", "unknown", true, "unknown"],
    ["done", "attention", true, "attention"],
    ["done", "broken", true, "broken"],
    ["done", "off", true, "not_verified"],
    ["todo", "works", true, "todo"],
    ["unknown", "works", true, "unknown"],
    ["done", "works", false, "done"], // шаг без проверки службы: «Готово» сам по себе
    ["todo", "works", false, "todo"],
  ] as const)("шаг %s, проверка %s, с карточкой=%s → %s", (step, state, hasCard, expected) => {
    expect(stepVerdict(step, hasCard ? fact(state) : undefined, hasCard)).toBe(expected);
  });

  it("шаг службы без ответа обзора — «Не удалось проверить», а не «Готово»", () => {
    expect(stepVerdict("done", undefined, true)).toBe("unknown");
  });

  it("в счёт «готово» входят только «Работает» и «Готово» шагов без проверки", () => {
    const ready = (["works", "done"] as const).every(isReady);
    const notReady = (
      ["todo", "not_verified", "stale", "unknown", "attention", "broken"] as const
    ).some(isReady);
    expect(ready).toBe(true);
    expect(notReady).toBe(false);
  });

  it("слово карточки — из ответа сервера; нет карточки или ответа — «Не удалось проверить»", () => {
    const overview = {
      checked_at: "2026-11-27T10:00:00Z",
      attention: [],
      cards: [
        {
          key: "mail",
          fact: fact("stale"),
          status: "unknown",
          access: "ok",
          note: "stale",
          count: null,
          amount_usd: null,
          last_activity_at: null,
        },
      ],
    } as IntegrationsOverview;
    expect(cardFact(overview, "mail").state).toBe("stale");
    expect(cardFact(overview, "erp")).toBe(UNKNOWN_FACT);
    expect(cardFact(undefined, "mail")).toBe(UNKNOWN_FACT);
  });

  it("шаги бота, почты, ERP и моделей привязаны к карточкам «Сервисов»", () => {
    expect(STEP_CARD).toEqual({ erp: "erp", bot: "telegram", mail: "mail", models: "models" });
  });
});
