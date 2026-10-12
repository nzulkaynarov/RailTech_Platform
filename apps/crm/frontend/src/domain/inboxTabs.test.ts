import { describe, expect, it } from "vitest";

import { type InboxTab, pickInboxTab, pickPreviewLead } from "./inboxTabs";

const ALL: InboxTab[] = ["handoffs", "mine", "unassigned", "requests"];
const NO_REQUESTS: InboxTab[] = ["handoffs", "mine", "unassigned"];

describe("inbox tab selection", () => {
  it.each<[string | null, Record<string, number>, InboxTab[], InboxTab]>([
    [null, { handoffs: 3, mine: 2 }, ALL, "handoffs"],
    [null, { handoffs: 0, mine: 2, unassigned: 1 }, ALL, "mine"],
    [null, { handoffs: 0, mine: 0, unassigned: 4 }, ALL, "unassigned"],
    [null, { requests: 1 }, ALL, "requests"],
    [null, {}, ALL, "handoffs"],
    ["mine", { handoffs: 3 }, ALL, "mine"],
    ["requests", { handoffs: 0, requests: 0 }, ALL, "requests"],
    ["requests", { mine: 1, requests: 5 }, NO_REQUESTS, "mine"],
    ["drop_table", { unassigned: 1 }, ALL, "unassigned"],
    [null, { requests: 2 }, NO_REQUESTS, "handoffs"],
  ])("tab=%s counts=%j → %s", (param, counts, available, expected) => {
    expect(pickInboxTab(param, counts, available)).toBe(expected);
  });
});

describe("preview lead from ?lead=", () => {
  it.each<[string | null, number | null]>([
    [null, null],
    ["12", 12],
    ["0", null],
    ["-3", null],
    ["1.5", null],
    ["12abc", null],
    ["", null],
    ["99999999999999999999", null],
  ])("lead=%s → %s", (param, expected) => {
    expect(pickPreviewLead(param)).toBe(expected);
  });
});
