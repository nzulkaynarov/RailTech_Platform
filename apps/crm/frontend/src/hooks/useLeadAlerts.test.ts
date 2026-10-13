import { afterEach, describe, expect, it, vi } from "vitest";

import { alertFor, PREF_KEY, readPref, writePref } from "./useLeadAlerts";
import type { CrmEvent } from "./useEventStream";

const mine: CrmEvent = {
  type: "message.created",
  lead_id: 7,
  role: "lead",
  assigned_user_id: 3,
};

describe("alertFor", () => {
  it.each([
    ["my lead, visible tab", mine, 3, true, false, "granted", { sound: true, notify: false }],
    ["my lead, hidden tab", mine, 3, true, true, "granted", { sound: true, notify: true }],
    ["hidden, no permission", mine, 3, true, true, "default", { sound: true, notify: false }],
    ["disabled in profile", mine, 3, false, true, "granted", { sound: false, notify: false }],
    ["someone else's lead", mine, 4, true, true, "granted", { sound: false, notify: false }],
    [
      "unassigned lead",
      { ...mine, assigned_user_id: null },
      3,
      true,
      true,
      "granted",
      { sound: false, notify: false },
    ],
    [
      "bot reply",
      { ...mine, role: "bot" },
      3,
      true,
      true,
      "granted",
      { sound: false, notify: false },
    ],
    [
      "manager reply",
      { ...mine, role: "manager" },
      3,
      true,
      true,
      "granted",
      { sound: false, notify: false },
    ],
    [
      "other event",
      { type: "lead.updated", lead_id: 7 },
      3,
      true,
      true,
      "granted",
      { sound: false, notify: false },
    ],
    ["not loaded me", mine, undefined, true, true, "granted", { sound: false, notify: false }],
  ] as const)("%s", (_name, event, myId, enabled, hidden, permission, expected) => {
    expect(alertFor(event, myId, enabled, hidden, permission)).toEqual(expected);
  });
});

describe("pref storage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.removeItem(PREF_KEY);
  });

  it("round-trips the choice", () => {
    expect(readPref()).toBe(false);
    writePref(true);
    expect(readPref()).toBe(true);
    writePref(false);
    expect(readPref()).toBe(false);
  });

  it("survives a storage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => {
      writePref(true);
    }).not.toThrow();
    expect(readPref()).toBe(false);
  });
});
