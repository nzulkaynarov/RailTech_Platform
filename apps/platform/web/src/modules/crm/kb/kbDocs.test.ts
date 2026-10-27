import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { KB_EXAMPLE_MD, KB_FORMAT_MD, KB_PROMPT_MD, kbPromptText } from "./kbDocs";

const read = (name: string) =>
  readFileSync(join(import.meta.dirname, "../../../../../../../docs/kb", name), "utf-8");

describe("тексты формата базы знаний в сборке", () => {
  it("совпадают с docs/kb (источник правды); обновить — `pnpm kb:sync`", () => {
    expect(KB_FORMAT_MD).toBe(read("FORMAT.md"));
    expect(KB_PROMPT_MD).toBe(read("PROMPT.md"));
    expect(KB_EXAMPLE_MD).toBe(read("example.md"));
  });

  it("промпт для копирования — блок из PROMPT.md без обрамления", () => {
    const text = kbPromptText();
    expect(text.startsWith("Ты готовишь документы")).toBe(true);
    expect(text).not.toContain("````");
    expect(read("PROMPT.md")).toContain(text);
  });
});
