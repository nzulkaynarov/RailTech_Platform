import { beforeEach, describe, expect, it } from "vitest";

import { readSeenIds, writeSeenIds } from "./prefs";

describe("показанное не повторяется", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("помнит показанные уведомления по сотруднику", () => {
    expect(readSeenIds("u1")).toBeNull();
    writeSeenIds("u1", ["erp:1", "crm:2"]);
    expect(readSeenIds("u1")).toEqual(["erp:1", "crm:2"]);
    expect(readSeenIds("u2")).toBeNull();
  });
});
