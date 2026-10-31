import { describe, expect, it } from "vitest";

import { MAX_FILE_BYTES } from "./fileSize";

describe("MAX_FILE_BYTES", () => {
  it("предел вложения — 25 МБ, как в EDS и BFF", () => {
    expect(MAX_FILE_BYTES).toBe(25 * 1024 * 1024);
  });
});
