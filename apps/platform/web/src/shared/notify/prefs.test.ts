import { beforeEach, describe, expect, it } from "vitest";

import { readSeen, writeSeen } from "./prefs";

describe("показанное не повторяется", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("помнит время самого нового показанного по сотруднику", () => {
    expect(readSeen("u1")).toBeNull();
    writeSeen("u1", 1_700_000_000_000);
    expect(readSeen("u1")).toBe(1_700_000_000_000);
    expect(readSeen("u2")).toBeNull();
  });
});
