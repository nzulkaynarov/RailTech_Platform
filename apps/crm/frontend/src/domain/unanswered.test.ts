import { describe, expect, it } from "vitest";

import type { MessageOut } from "../api/generated/model";
import { lastUnanswered } from "./unanswered";

const msg = (id: number, role: string, text: string): MessageOut => ({
  id,
  role,
  text,
  attachments: [],
  sent_by_user_id: null,
  created_at: "2026-10-12T11:00:00Z",
  meta: {},
});

describe("lastUnanswered", () => {
  it.each([
    [[msg(1, "manager", "Здравствуйте"), msg(2, "lead", "вагон борми?")], "вагон борми?"],
    [[msg(1, "lead", "вопрос"), msg(2, "manager", "ответ")], null],
    [[msg(1, "lead", "вопрос"), msg(2, "bot", "ответ бота")], null],
    [[], null],
    [undefined, null],
  ])("%#", (messages, expected) => {
    expect(lastUnanswered(messages)).toBe(expected);
  });

  it("shortens long messages", () => {
    const text = "а".repeat(200);
    expect(lastUnanswered([msg(1, "lead", text)])?.length).toBe(141);
  });
});
