import { describe, expect, it } from "vitest";

import { t } from "../i18n/ru";
import { applyAssist, canAssist, needsReplaceConfirm } from "./replyAssist";

describe("replyAssist", () => {
  it.each([
    ["draft", "", true],
    ["draft", "текст", true],
    ["improve", "", false],
    ["improve", "   ", false],
    ["improve", "текст", true],
  ] as const)("canAssist(%s, %j) = %s", (mode, draft, expected) => {
    expect(canAssist(mode, draft)).toBe(expected);
  });

  it.each([
    ["draft", "", false],
    ["draft", "  ", false],
    ["draft", "уже написал", true],
    ["improve", "уже написал", false],
  ] as const)("needsReplaceConfirm(%s, %j) = %s", (mode, draft, expected) => {
    expect(needsReplaceConfirm(mode, draft)).toBe(expected);
  });

  it("draft replaces the box without undo", () => {
    expect(
      applyAssist("draft", "", { text: "Здравствуйте!", cost_usd: 0.01, notice: null }),
    ).toEqual({
      text: "Здравствуйте!",
      undo: null,
      info: t.lead.assist.ready,
    });
  });

  it("draft with removed numbers explains why", () => {
    const out = applyAssist("draft", "", { text: "Пришлём договор.", notice: "numbers_removed" });
    expect(out.info).toBe(t.lead.assist.numbersRemoved);
  });

  it("improve keeps the original for undo", () => {
    expect(applyAssist("improve", "привет", { text: "Привет!", notice: null })).toEqual({
      text: "Привет!",
      undo: "привет",
      info: t.lead.assist.ready,
    });
  });

  it("improve rejected for new numbers keeps the text and offers no undo", () => {
    expect(applyAssist("improve", "завтра", { text: "завтра", notice: "new_numbers" })).toEqual({
      text: "завтра",
      undo: null,
      info: t.lead.assist.newNumbers,
    });
  });
});
