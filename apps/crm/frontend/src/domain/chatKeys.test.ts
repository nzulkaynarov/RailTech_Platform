import { describe, expect, it } from "vitest";

import { type ChatKey, chatKeyAction, messageLang } from "./chatKeys";

const key = (patch: Partial<ChatKey> = {}): ChatKey => ({
  key: "Enter",
  shiftKey: false,
  ctrlKey: false,
  metaKey: false,
  ...patch,
});

describe("chatKeyAction", () => {
  it.each([
    ["desktop Enter", key(), false, "send"],
    ["desktop Shift+Enter", key({ shiftKey: true }), false, "newline"],
    ["desktop Ctrl+Enter", key({ ctrlKey: true }), false, "send"],
    ["desktop Cmd+Enter", key({ metaKey: true }), false, "send"],
    ["touch Enter", key(), true, "newline"],
    ["touch Shift+Enter", key({ shiftKey: true }), true, "newline"],
    ["touch Ctrl+Enter (hardware keyboard)", key({ ctrlKey: true }), true, "send"],
    ["IME composition", key({ isComposing: true }), false, "none"],
    ["other key", key({ key: "a" }), false, "none"],
  ] as const)("%s → %s", (_, event, touch, action) => {
    expect(chatKeyAction(event, touch)).toBe(action);
  });
});

describe("messageLang", () => {
  it.each([
    ["lead", "uz", "uz"],
    ["lead", "EN", "en"],
    ["lead", "ru", "ru"],
    ["lead", "kk", undefined],
    ["bot", "uz", undefined],
    ["manager", "en", undefined],
    ["lead", undefined, undefined],
  ])("%s in %s → %s", (role, language, lang) => {
    expect(messageLang(role, language)).toBe(lang);
  });
});
