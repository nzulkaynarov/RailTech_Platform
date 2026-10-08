import { describe, expect, it } from "vitest";

import { keysFor, parseSse } from "./useEventStream";

describe("parseSse", () => {
  it("splits complete events and keeps the tail", () => {
    const input =
      'retry: 3000\n\nevent: lead.updated\ndata: {"type":"lead.updated","lead_id":5}\n\n: keepalive\n\nevent: mess';
    const { events, rest } = parseSse(input);
    expect(events).toEqual([{ type: "lead.updated", lead_id: 5 }]);
    expect(rest).toBe("event: mess");
  });

  it("skips broken payloads", () => {
    expect(parseSse("data: {oops\n\n").events).toEqual([]);
  });
});

describe("keysFor", () => {
  it("invalidates the lead and lists", () => {
    expect(keysFor({ type: "message.created", lead_id: 7 })).toEqual([
      ["inbox"],
      ["leads"],
      ["lead", 7],
    ]);
  });
});
